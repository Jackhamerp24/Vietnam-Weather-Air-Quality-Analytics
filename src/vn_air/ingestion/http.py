"""Bounded HTTPS requests; caller persists every attempt before retrying."""

import json
import os
import random
import re
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, quote_plus, urlsplit

import certifi
import httpx

from vn_air.ingestion import IngestionError


PATHS = {
    "api.openaq.org": r"/v3/(locations/[1-9][0-9]*|licenses/[1-9][0-9]*|sensors/[1-9][0-9]*/hours)",
    "api.open-meteo.com": r"/v1/forecast",
    "archive-api.open-meteo.com": r"/v1/archive",
    "air-quality-api.open-meteo.com": r"/v1/air-quality",
}
PARAMETERS = {
    "openaq": {"datetime_from", "datetime_to", "limit", "page"},
    "open_meteo": {"latitude", "longitude", "hourly", "start_date", "end_date", "models", "domains",
                   "timezone", "timeformat", "wind_speed_unit", "temperature_unit", "precipitation_unit"},
}


def now():
    return datetime.now(timezone.utc)


def decode_json(body):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    try:
        payload = json.loads(body, object_pairs_hook=unique)
        if not isinstance(payload, dict):
            raise ValueError("object_required")
        return payload
    except (ValueError, UnicodeError, RecursionError):
        raise IngestionError("invalid_json") from None


@dataclass
class Attempt:
    requested_at: datetime
    retrieved_at: datetime
    http_status: int | None
    body: bytes | None
    media_type: str | None
    error_code: str | None
    elapsed_ms: int
    retry_after_seconds: float | None


class HTTPSource:
    def __init__(self, *, key=None, secrets=(), transport=None, sleep=time.sleep, max_bytes=2 * 1024 * 1024):
        self.key = key
        self.sleep = sleep
        self.max_bytes = max_bytes
        self.secrets = {variant for secret in (*secrets, key) if secret
                        for variant in (secret, quote(secret, safe=""), quote_plus(secret))}
        context = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or certifi.where())
        self.client = httpx.Client(
            verify=context, transport=transport, follow_redirects=False, trust_env=False,
            timeout=httpx.Timeout(connect=10, read=45, write=10, pool=10),
            headers={"User-Agent": "VietnamEnvironmentalAnalytics/0.3", "Accept": "application/json"},
        )

    def close(self):
        self.client.close()

    def validate(self, url, parameters):
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname not in PATHS or parsed.port not in (None, 443)
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or not re.fullmatch(PATHS[parsed.hostname], parsed.path)):
            raise IngestionError("unapproved_endpoint")
        group = "openaq" if parsed.hostname == "api.openaq.org" else "open_meteo"
        if set(parameters) - PARAMETERS[group]:
            raise IngestionError("unapproved_parameters")
        serialized = json.dumps(parameters, ensure_ascii=False)
        if any(secret in serialized for secret in self.secrets):
            raise IngestionError("credential_in_parameters")
        if group == "openaq" and not self.key:
            raise IngestionError("openaq_key_missing")
        return group

    def get(self, url, parameters, *, before_attempt, save_attempt):
        group = self.validate(url, parameters)
        for number in range(1, 5):
            before_attempt(group)
            started, tick = now(), time.monotonic()
            status, body, media, code, retry_after = None, None, None, None, None
            headers = {"X-API-Key": self.key} if group == "openaq" and self.key else {}
            try:
                with self.client.stream("GET", url, params=parameters, headers=headers) as response:
                    status = response.status_code
                    content_type = response.headers.get("content-type", "").split(";", 1)[0]
                    media = content_type if content_type in {"application/json", "text/plain", "text/html", "application/octet-stream"} else None
                    retry = response.headers.get("retry-after")
                    if retry:
                        try:
                            retry_after = max(0.0, float(retry) if retry.isdigit() else (parsedate_to_datetime(retry) - now()).total_seconds())
                        except (ValueError, TypeError, OverflowError):
                            retry_after = None
                    elif status == 429:
                        reset = response.headers.get("x-ratelimit-reset", "")
                        if reset.isdigit():
                            retry_after = float(reset)
                    buffer = bytearray()
                    for chunk in response.iter_bytes(chunk_size=16384):
                        if time.monotonic() - tick > 120:
                            code = "response_deadline"
                            break
                        if len(buffer) + len(chunk) > self.max_bytes:
                            code = "response_too_large"
                            break
                        buffer.extend(chunk)
                    if code is None:
                        body = bytes(buffer)
                        readable = body.decode("utf-8", errors="replace")
                        # Detect Unicode-escaped echoes as well as literal and URL-encoded secrets.
                        try:
                            readable += json.dumps(json.loads(body), ensure_ascii=False)
                        except (ValueError, UnicodeError, RecursionError):
                            pass
                        if any(secret in readable for secret in self.secrets):
                            body, code = None, "credential_echo"
                    if code is None and status != 200:
                        code = "redirect_blocked" if 300 <= status < 400 else f"http_{status}"
            except httpx.TimeoutException:
                code, body = "timeout", None
            except httpx.HTTPError:
                code, body = "network_error", None
            attempt = Attempt(started, now(), status, body, media, code,
                              round(1000 * (time.monotonic() - tick)), retry_after)
            response_id = save_attempt(attempt, number, group)
            if code is None:
                return response_id, attempt
            transient = code in {"timeout", "network_error"} or (code.startswith("http_") and status is not None and (status == 429 or status >= 500))
            if not transient or number == 4:
                raise IngestionError(code)
            wait = max(2 ** number + random.uniform(0, 1), retry_after or 0)
            if wait > 300:
                # Fail rather than retry before the provider's long cooldown expires.
                raise IngestionError("provider_cooldown")
            self.sleep(wait)
        raise IngestionError("retry_exhausted")
