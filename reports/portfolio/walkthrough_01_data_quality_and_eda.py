"""Walkthrough 01: frozen window, source separation, coverage gaps and EDA.

Reads only pinned Phase 4 and Phase 5 artifacts, verifies every consumed hash
before presenting a value, and never imputes or recalculates a source value.
"""

# %% Imports and artifact contract
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import portfolio_common as pc

ID = "01_data_quality_and_eda"
TITLE = "Data quality, coverage gaps and descriptive EDA"
COMMAND = pc.INDIVIDUAL_COMMAND.format(module="walkthrough_01_data_quality_and_eda")


# %% Hash-verified projection
def build() -> tuple[dict, str]:
    checks: list[dict] = []

    phase4_path = pc.verify_file(
        "docs/verification/phase_4_quality_2026-09-07_final.json", checks
    )
    phase4 = pc.read_json(phase4_path)
    manifest = phase4["manifest"]
    pc.require(
        pc.same_timestamp(manifest["start"], pc.FROZEN_WINDOW["start"])
        and pc.same_timestamp(manifest["end"], pc.FROZEN_WINDOW["end"])
        and pc.same_timestamp(manifest["cutoff"], pc.FROZEN_WINDOW["cutoff"]),
        "Phase 4 frozen window does not match the declared boundary",
    )
    pc.require(
        manifest["schema_revision"] == pc.SCHEMA_REVISION,
        "Phase 4 schema revision does not match",
    )

    phase5 = pc.load_artifact("phase5", checks)
    eda_path = pc.payload(phase5, "eda_summary.json", checks)
    bundle_path = pc.payload(phase5, "eda_bundle.json", checks)
    daily_path = pc.payload(phase5, "daily.csv", checks)
    grid_path = pc.payload(phase5, "hourly_pm25_weather_grid.csv", checks)
    eda = pc.read_json(eda_path)
    bundle = pc.read_json(bundle_path)

    pc.require(
        bundle["bundle_sha256"] == pc.IDENTITIES["phase5_bundle_digest"],
        "Phase 5 bundle digest does not match the pinned identity",
    )
    pc.require(
        pc.digest_without(bundle, "bundle_sha256")
        == pc.IDENTITIES["phase5_bundle_digest"],
        "Phase 5 bundle content does not recompute to its digest",
    )
    pc.require(
        bundle["manifest"]["phase4_artifact_sha256"] == pc.sha256_file(phase4_path),
        "Phase 5 bundle is not bound to the consumed Phase 4 artifact bytes",
    )
    pc.require(
        eda["bundle_sha256"] == pc.IDENTITIES["phase5_bundle_digest"],
        "Phase 5 EDA summary is not bound to the frozen bundle",
    )
    pc.require(
        eda["manifest"]["eda_version"] == pc.IDENTITIES["phase5_eda_version"],
        "Unexpected Phase 5 EDA version",
    )

    daily_rows = pc.read_csv_rows(daily_path)
    grid_rows = pc.read_csv_rows(grid_path)
    accepted = sum(1 for row in grid_rows if row["quality"] == "accepted")
    absent = sum(1 for row in grid_rows if row["quality"] == "absent")
    qualified_days = sum(1 for row in daily_rows if row["qualified_mean"])
    pc.require(
        accepted == 4191 and absent == 129,
        f"Hourly grid reconciliation failed: accepted={accepted}, absent={absent}",
    )
    pc.require(
        len(daily_rows) == 182 and qualified_days == 172,
        "Daily qualification reconciliation failed",
    )

    summary = eda["summary"]
    sensors = []
    for sensor_id in sorted(summary["sensors"]):
        sensor = summary["sensors"][sensor_id]
        coverage = phase4["measurements"][sensor_id]["accepted_coverage"]
        distribution = sensor["pm25"]
        lag_one = next(
            entry
            for entry in sensor["lag_correlations"]
            if int(entry["lag_hours"]) == 1
        )
        wind = next(
            entry
            for entry in sensor["weather_associations"]
            if entry["variable"] == "wind_speed_10m"
        )
        sensors.append(
            {
                "sensor_id": sensor_id,
                "name": sensor["name"],
                "location_id": sensor["location_id"],
                "attribution": sensor["attribution"],
                "expected_hours": coverage["expected_hours"],
                "accepted_hours": coverage["present_hours"],
                "completeness_percent": coverage["completeness_percent"],
                "longest_missing_run_hours": coverage["longest_missing_run_hours"],
                "missing_runs": len(coverage["missing_runs"]),
                "complete_weather_hours": sensor["complete_weather_hours"],
                "pm25_ug_m3": distribution,
                "lag1_pearson": lag_one["pearson_r"],
                "lag1_n": lag_one["n"],
                "wind_speed_pearson": wind["pearson_r"],
                "wind_speed_n": wind["n"],
            }
        )

    results = {
        "schema_revision": pc.SCHEMA_REVISION,
        "phase4_artifact_sha256": pc.sha256_file(phase4_path),
        "phase5_bundle_digest": bundle["bundle_sha256"],
        "sensors": sensors,
        "common_accepted_sensor_hours": summary["common_accepted_sensor_hours"],
        "hourly_grid": {
            "rows": len(grid_rows),
            "accepted": accepted,
            "absent": absent,
        },
        "daily_rows": len(daily_rows),
        "qualified_full_days": qualified_days,
        "forecast_captures_not_analyzed": summary["forecast_captures_not_analyzed"],
        "missing_policy": (
            "Missing hours remain null and unplotted; no interpolation and no "
            "substitution with modeled values."
        ),
        "quality_findings": {
            "provisional_accepted_selected_hours": 4191,
            "revision_transitions_value_changing": sum(
                entry["revision_handling"]["transitions"].get(
                    "value_changing_transitions", 0
                )
                for entry in phase4["measurements"].values()
            ),
            "interval_errors": sum(
                entry["interval_errors"]
                for entry in phase4["measurements"].values()
            ),
            "quarantines_visible": phase4["preexisting_quality_issues"][
                "station_timezone_changed"
            ],
            "failed_runs_at_cutoff": phase4["ingestion_run_statuses_at_cutoff"][
                "failed"
            ],
        },
    }

    markdown = render(results)
    payload = pc.base_payload(ID, COMMAND)
    payload["inputs"] = checks
    payload["status"] = "ok"
    payload["results"] = results
    return payload, markdown


# %% Markdown presentation
def render(results: dict) -> str:
    lines = [
        f"# Walkthrough 01: {TITLE}",
        "",
        f"Command: `{COMMAND}`",
        "",
        "Window: "
        f"{pc.FROZEN_WINDOW['start']} to {pc.FROZEN_WINDOW['end']} "
        f"(cutoff {pc.FROZEN_WINDOW['cutoff']}); schema "
        f"`{results['schema_revision']}`.",
        "",
        "Everything below is a descriptive quality or EDA statement. No "
        "significance, causal or forecast-skill claim is made.",
        "",
        "## Sensor coverage (Phase 4)",
        "",
        pc.md_table(
            ["Sensor", "Location", "Accepted / expected", "Completeness", "Longest gap"],
            [
                [
                    sensor["name"],
                    sensor["location_id"],
                    f"{sensor['accepted_hours']} / {sensor['expected_hours']}",
                    f"{sensor['completeness_percent']}%",
                    f"{sensor['longest_missing_run_hours']} h",
                ]
                for sensor in results["sensors"]
            ],
        ),
        "",
        f"The two sensors share {results['common_accepted_sensor_hours']} accepted "
        "hours (one observation from each sensor per hour). They are site-level "
        "records, not city averages. Missing "
        "periods stay visible: "
        + "; ".join(
            f"{sensor['name']} has {sensor['missing_runs']} missing run(s) "
            f"with a longest gap of {sensor['longest_missing_run_hours']} h"
            for sensor in results["sensors"]
        )
        + ".",
        "",
        "## Descriptive hourly PM2.5 (ug/m3; Phase 5, accepted hours only)",
        "",
        pc.md_table(
            ["Sensor", "n", "Mean", "Median", "IQR (p25-p75)", "Maximum"],
            [
                [
                    sensor["name"],
                    str(sensor["pm25_ug_m3"]["n"]),
                    pc.fmt(sensor["pm25_ug_m3"]["mean"]),
                    pc.fmt(sensor["pm25_ug_m3"]["median"]),
                    f"{pc.fmt(sensor['pm25_ug_m3']['p25'])}-{pc.fmt(sensor['pm25_ug_m3']['p75'])}",
                    pc.fmt(sensor["pm25_ug_m3"]["maximum"]),
                ]
                for sensor in results["sensors"]
            ],
        ),
        "",
        pc.md_table(
            ["Sensor", "Lag-1 PM2.5 r (n)", "Wind-speed r (n)", "Complete ERA5 hours"],
            [
                [
                    sensor["name"],
                    f"{pc.fmt(sensor['lag1_pearson'])} ({sensor['lag1_n']})",
                    f"{pc.fmt(sensor['wind_speed_pearson'])} ({sensor['wind_speed_n']})",
                    str(sensor["complete_weather_hours"]),
                ]
                for sensor in results["sensors"]
            ],
        ),
        "",
        "Lag and weather values are descriptive pairwise statistics over one "
        "90-day window. They do not adjust for season, time of day, "
        "autocorrelation or sensor bias.",
        "",
        f"Daily grid: {results['daily_rows']} sensor-days, including partial and "
        f"unqualified dates. Qualified means exist for {results['qualified_full_days']} "
        "full 24-hour Vietnam-local sensor-days with at least 18 accepted hours. "
        "Unqualified daily means stay null in qualified charts.",
        "",
        "## Source separation and missing-data policy",
        "",
        "- Measured: OpenAQ PM2.5 at CMT8 and OceanPark (CC BY 4.0 credits in "
        "the artifact metadata).",
        "- Reanalysis: ERA5 weather is retrospective context, not what a "
        "forecaster had at the historical time.",
        "- Forecast: Open-Meteo forecast snapshots stay in provenance metadata "
        f"and do not enter the retrospective weather table "
        f"({results['forecast_captures_not_analyzed']} capture groups recorded).",
        "- Modeled: CAMS remains a separate modeled stream, including "
        "modeled-only Da Nang.",
        f"- {results['missing_policy']}",
        "",
        "## Quality audit findings",
        "",
        f"- Selected measured hours: "
        f"{results['quality_findings']['provisional_accepted_selected_hours']} "
        "provisionally accepted.",
        f"- Value-changing revision transitions: "
        f"{results['quality_findings']['revision_transitions_value_changing']}.",
        f"- Interval errors: {results['quality_findings']['interval_errors']}.",
        f"- Visible quarantines: "
        f"{results['quality_findings']['quarantines_visible']}; failed runs at "
        f"cutoff: {results['quality_findings']['failed_runs_at_cutoff']}.",
        "",
        "## Labels",
        "",
        "- Coverage and EDA outputs: descriptive_only.",
        "- Lag and weather associations: exploratory pairwise statistics.",
        "",
        "Evidence: Phase 4 artifact "
        f"`{results['phase4_artifact_sha256']}`; Phase 5 bundle "
        f"`{results['phase5_bundle_digest']}`.",
        "",
    ]
    return "\n".join(lines)


# %% Command-line execution
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=TITLE)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    output_dir = pc.ensure_new_dir(Path(args.output_dir))
    payload, markdown = build()
    hashes = pc.write_artifacts(output_dir, ID, payload, markdown)
    print(f"OK {ID}: {len(payload['inputs'])} inputs verified")
    for name, value in sorted(hashes.items()):
        print(f"  {name} {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
