"""Explicit process environments and a non-executing operator-file parser."""

import os
import stat
from pathlib import Path


RUNTIME_NAMES = frozenset({"PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR", "TMP", "TEMP"})
INGESTION_NAMES = frozenset({"DATABASE_URL", "OPENAQ_API_KEY"})
HTTP_TRUST_NAMES = frozenset({"SSL_CERT_FILE", "SSL_CERT_DIR"})
MAX_OPERATOR_FILE_BYTES = 16384


class OperatorEnvironmentError(ValueError):
    """A constant diagnostic code, never an input value or file contents."""


def safe_runtime_environment(environ):
    return {key: value for key, value in environ.items()
            if key in RUNTIME_NAMES and isinstance(value, str)}


def ingestion_environment(environ, source_dir):
    result = safe_runtime_environment(environ)
    for key in INGESTION_NAMES | HTTP_TRUST_NAMES:
        if isinstance(environ.get(key), str):
            result[key] = environ[key]
    result["PYTHONPATH"] = str(source_dir)
    return result


def read_operator_environment(path, *, checkout):
    """Read exactly two literal KEY=value assignments without shell evaluation."""
    path = Path(path)
    checkout = Path(checkout).resolve()
    if path.name == ".env" or path.name.startswith(".env."):
        raise OperatorEnvironmentError("operator_environment_unsafe_path")
    if path.resolve().is_relative_to(checkout):
        raise OperatorEnvironmentError("operator_environment_inside_checkout")
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > MAX_OPERATOR_FILE_BYTES):
            raise OperatorEnvironmentError("operator_environment_unsafe_file")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            raw = handle.read(MAX_OPERATOR_FILE_BYTES + 1)
        if len(raw) > MAX_OPERATOR_FILE_BYTES:
            raise OperatorEnvironmentError("operator_environment_too_large")
        content = raw.decode("utf-8")
    except (OSError, UnicodeError):
        raise OperatorEnvironmentError("operator_environment_unreadable") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    result = {}
    for line in content.split("\n"):
        line = line.removesuffix("\r")
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if not separator or name not in INGESTION_NAMES or name in result:
            raise OperatorEnvironmentError("operator_environment_invalid_assignment")
        if (not value or any(not 33 <= ord(c) <= 126 for c in value)
                or any(c in value for c in "\"'`$\\;")):
            raise OperatorEnvironmentError("operator_environment_invalid_value")
        result[name] = value
    if set(result) != INGESTION_NAMES:
        raise OperatorEnvironmentError("operator_environment_missing_assignment")
    return result
