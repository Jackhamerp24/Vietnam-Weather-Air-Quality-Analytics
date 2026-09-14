"""Shared, read-only helpers for the Phase 12 portfolio walkthroughs.

Every walkthrough is a presentation layer over frozen Phase 4-9 artifacts.
The helpers here verify pinned SHA-256 identities before a single value is
presented. They never open a database, make network calls, read ``.env`` or
fit a model. Deterministic output is promised: generated JSON and Markdown
depend only on artifact bytes and this module, never on the wall clock or the
output path.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

WALKTHROUGH_VERSION = "phase12_walkthroughs_v2"
RUNNER_COMMAND = (
    "python3 -B reports/portfolio/run_walkthroughs.py --output-dir <output-dir>"
)
INDIVIDUAL_COMMAND = (
    "python3 -B reports/portfolio/{module}.py --output-dir <output-dir>"
)

REPO_ROOT = Path(__file__).resolve().parents[2]

FROZEN_WINDOW = {
    "cutoff": "2026-09-06T20:59:00.669630Z",
    "start": "2026-06-08T00:00:00Z",
    "end": "2026-09-06T00:00:00Z",
    "storage_timezone": "UTC timestamptz",
    "display_timezone": "Vietnam local dates (UTC+07:00) for daily qualification",
}

SCHEMA_REVISION = "0003_response_integrity"

PINNED_FILES = {
    "docs/verification/phase_4_quality_2026-09-07_final.json": (
        "c1570b8679b4385d693bb08ab960e4d0564c8315d52e99cf5231d13ce97b3713"
    ),
    "docs/verification/phase_5_eda_2026-09-07_final/SUCCESS.json": (
        "e32a3ae84bf236504c4b183e277beccbc9682f4811f2e5c8956975f9ac3c4e89"
    ),
    "docs/verification/phase_6_statistics_2026-09-09_corrected/SUCCESS.json": (
        "017a901cb68a58f06e7fbc68e81bc17d76b4db675fe0032109907ec38a3bb4f3"
    ),
    "docs/verification/phase_7_features_2026-09-10_structural_hardened/SUCCESS.json": (
        "a7ea4cb56d378766ca83561d9e290bec3703ac161b88f69d4200ff155fbd2297"
    ),
    "docs/verification/phase_8_baselines_2026-09-11_v2_verified/SUCCESS.json": (
        "d178890fa503752e03ee09cd2d9633d1bcfc76af9d8f3365a02d63e5d06da336"
    ),
    "docs/verification/phase_9_models_2026-09-12_comparison_hardened/SUCCESS.json": (
        "68bdad7e7cc244bde48899b9fbb9934fbba8604aa9c11634d78a705945bcadad"
    ),
    "dashboard/data/dashboard.json": (
        "d2c017952150828f30a1a6617940983ece43c06c20aa4498a44d933046fe131d"
    ),
}

ARTIFACTS = {
    "phase5": "docs/verification/phase_5_eda_2026-09-07_final",
    "phase6": "docs/verification/phase_6_statistics_2026-09-09_corrected",
    "phase7": "docs/verification/phase_7_features_2026-09-10_structural_hardened",
    "phase8": "docs/verification/phase_8_baselines_2026-09-11_v2_verified",
    "phase9": "docs/verification/phase_9_models_2026-09-12_comparison_hardened",
}

IDENTITIES = {
    "phase5_eda_version": "phase5_eda_v1",
    "phase5_bundle_digest": (
        "92370a857153f2d2a476ab35dbceab3873503239ad6211170e99b8075d1e9e63"
    ),
    "phase6_stats_version": "phase6_statistics_v2",
    "phase6_manifest_digest": (
        "71f7b17bff4bd43a406d235bbc585a268ec56b07f2554cc2b19939b5b5dcf918"
    ),
    "phase7_feature_version": "phase7_features_v7",
    "phase7_manifest_digest": (
        "6aa92f0add8046379445c2f3b5beb77fa2ad05cc981a43f6ca61f1af4fcf60aa"
    ),
    "phase8_baseline_version": "phase8_baselines_v2",
    "phase8_manifest_digest": (
        "ec651c4df04cb605f8849c1af96a3aea58f0902370e16ec39b9c48fdee22775e"
    ),
    "phase9_model_version": "phase9_ml_v4",
    "phase9_manifest_digest": (
        "378f2e7f34476fe885ce6ec9827b7a48c346706f36b548fbc8db78ce94d8a770"
    ),
    "dashboard_canonical_digest": (
        "b3b43813751628cc0d3439c209484a7c588cbdc9f355eb38cbe9233b1e0a167d"
    ),
}

LABELS = {
    "inferential": (
        "adjusted Phase 6 family results justified by Holm or Benjamini-Hochberg"
    ),
    "exploratory": (
        "unadjusted or sensitivity output that is not the primary inferential claim"
    ),
    "descriptive_only": "coverage, diagnostics and Phase 8-9 comparisons",
    "limited_diagnostic": (
        "the frozen Phase 7-9 artifact status caused by missing prospectively "
        "captured PM/history and forecast-weather evidence"
    ),
}


class WalkthroughError(RuntimeError):
    """Raised when an input is missing, mismatched or contract-violating."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise WalkthroughError(message)


def canonical_timestamp(value: str) -> str:
    return value[:-1] + "+00:00" if value.endswith("Z") else value


def same_timestamp(left: str, right: str) -> bool:
    return canonical_timestamp(left) == canonical_timestamp(right)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def digest(value) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def digest_without(value, key: str) -> str:
    return digest({k: v for k, v in value.items() if k != key})


def read_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WalkthroughError(f"Invalid JSON input {path}: {error}") from error


def read_csv_rows(path: Path) -> list[dict]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError as error:
        raise WalkthroughError(f"Invalid CSV input {path}: {error}") from error


def resolve_repo_path(relative: str) -> Path:
    relative_path = Path(relative)
    require(not relative_path.is_absolute() and ".." not in relative_path.parts,
            "Input path must be repository-relative")
    path = REPO_ROOT
    for component in relative_path.parts:
        path = path / component
        require(not path.is_symlink(), f"Symlinked input is not allowed: {relative}")
    path = path.resolve()
    require(
        path == REPO_ROOT or REPO_ROOT in path.parents,
        f"Input path escapes the repository: {relative}",
    )
    return path


def verify_file(relative: str, checks: list[dict], expected: str | None = None) -> Path:
    expected = expected if expected is not None else PINNED_FILES.get(relative)
    require(expected is not None, f"No pinned hash declared for {relative}")
    path = resolve_repo_path(relative)
    require(path.is_file(), f"Missing pinned input: {relative}")
    observed = sha256_file(path)
    require(
        observed == expected,
        f"Hash mismatch for {relative}: observed {observed}, expected {expected}",
    )
    checks.append(
        {
            "path": relative,
            "sha256": observed,
            "expected_sha256": expected,
            "verified": True,
        }
    )
    return path


def load_artifact(name: str, checks: list[dict]) -> dict:
    relative_dir = ARTIFACTS[name]
    success_path = verify_file(f"{relative_dir}/SUCCESS.json", checks)
    success = read_json(success_path)
    return {
        "name": name,
        "relative_dir": relative_dir,
        "dir": REPO_ROOT / relative_dir,
        "success": success,
    }


def payload(artifact: dict, filename: str, checks: list[dict]) -> Path:
    relative = f"{artifact['relative_dir']}/{filename}"
    declared = artifact["success"].get("files_sha256", {}).get(filename)
    require(
        declared is not None,
        f"{artifact['name']} SUCCESS.json does not declare {filename}",
    )
    return verify_file(relative, checks, declared)


def expect_manifest_digest(summary: dict, identity_key: str) -> None:
    declared = summary.get("manifest_sha256")
    observed = digest(summary.get("manifest", {}))
    require(
        declared == observed == IDENTITIES[identity_key],
        f"Manifest digest mismatch for {identity_key}: "
        f"declared {declared}, observed {observed}, "
        f"expected {IDENTITIES[identity_key]}",
    )


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def fmt(value) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def ensure_new_dir(path: Path) -> Path:
    require(not any(part.is_symlink() for part in (path, *path.parents)),
            "Symlinked output directory is not allowed")
    try:
        path.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise WalkthroughError(
            f"Output directory already exists; choose a new path: {path}"
        ) from error
    return path


def write_text_new(path: Path, text: str) -> None:
    require(not any(part.is_symlink() for part in path.parents),
            "Symlinked output parent is not allowed")
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(text)
    except FileExistsError as error:
        raise WalkthroughError(f"Refusing to overwrite existing output: {path}") from error


def write_artifacts(
    output_dir: Path, name: str, payload: dict, markdown: str
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_name = f"{name}.json"
    md_name = f"{name}.md"
    json_path = output_dir / json_name
    md_path = output_dir / md_name
    if any(path.exists() or path.is_symlink() for path in (json_path, md_path)):
        raise WalkthroughError(
            f"Refusing to overwrite existing output in {output_dir}"
        )
    json_text = json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n"
    write_text_new(json_path, json_text)
    write_text_new(md_path, markdown)
    return {
        json_name: sha256_file(json_path),
        md_name: sha256_file(md_path),
    }


def base_payload(walkthrough_id: str, command: str) -> dict:
    return {
        "walkthrough": walkthrough_id,
        "walkthrough_version": WALKTHROUGH_VERSION,
        "command": command,
        "frozen_window": FROZEN_WINDOW,
        "source_separation": {
            "measured": "OpenAQ PM2.5 at CMT8 and OceanPark; not city averages",
            "reanalysis": "ERA5 retrospective weather context; not operational availability",
            "forecast": "Open-Meteo forecast snapshots; not ground truth",
            "modeled": "CAMS modeled air-quality context; never a measured replacement",
        },
        "labels": LABELS,
    }
