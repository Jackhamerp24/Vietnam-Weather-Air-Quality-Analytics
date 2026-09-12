"""Explicit database setup commands. Never print credentials or SQL parameters."""

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from vn_air.config import load_config
from vn_air.database.setup import database_engine, migrate, seed_reference_data
from vn_air.ingestion import IngestionError
from vn_air.ingestion.parsing import timestamp
from vn_air.ingestion.pipeline import Ingestor, PRODUCTS


def audit_timestamp(value):
    try:
        return timestamp(value)
    except IngestionError:
        raise argparse.ArgumentTypeError("Use an offset-aware ISO timestamp") from None


def main():
    parser = argparse.ArgumentParser(prog="vn-air")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-config")
    validate.add_argument("path", type=Path)
    database = commands.add_parser("db")
    actions = database.add_subparsers(dest="action", required=True)
    actions.add_parser("upgrade")
    actions.add_parser("status")
    seed = actions.add_parser("seed")
    seed.add_argument("--config", type=Path, required=True)
    ingest = commands.add_parser("ingest", help="Bounded ingestion; no scheduler or automatic migration")
    ingest.add_argument("mode", choices=("backfill", "poll"))
    ingest.add_argument("--source", choices=tuple(PRODUCTS), required=True)
    ingest.add_argument("--config", type=Path, default=Path("configs/study.json"))
    ingest.add_argument("--start", type=timestamp, help="Inclusive UTC interval start, e.g. 2026-06-08T00:00:00Z")
    ingest.add_argument("--end", type=timestamp, help="Exclusive interval end; OpenAQ includes the period ending here")
    ingest.add_argument("--target", action="append", default=[], help="Configured sensor ID for OpenAQ, location ID for models")
    ingest.add_argument("--resume", action="store_true", help="Skip completed historical target/window checkpoints")
    ingest.add_argument("--max-requests", type=int, default=250)
    report = commands.add_parser("report", help="Read-only ingestion counts, provenance and storage summary")
    report.add_argument("--output", type=Path, help="Optional NEW JSON evidence file; parent must exist")
    quality = commands.add_parser("data-quality", help="Frozen, read-only Phase 4 data-quality audits")
    quality_actions = quality.add_subparsers(dest="quality_action", required=True)
    audit = quality_actions.add_parser("audit")
    audit.add_argument("--cutoff", type=audit_timestamp, required=True, help="UTC cutoff for response and revision eligibility")
    audit.add_argument("--start", type=audit_timestamp, required=True, help="Inclusive UTC measurement window start")
    audit.add_argument("--end", type=audit_timestamp, required=True, help="Exclusive UTC measurement window end")
    audit.add_argument("--config", type=Path, default=Path("configs/study.json"))
    audit.add_argument("--output", type=Path, required=True, help="NEW JSON audit artifact; parent must exist")
    eda = commands.add_parser("eda", help="Phase 5 descriptive exploratory data analysis")
    eda_actions = eda.add_subparsers(dest="eda_action", required=True)
    eda_run = eda_actions.add_parser("run")
    eda_run.add_argument("--cutoff", type=audit_timestamp, required=True)
    eda_run.add_argument("--start", type=audit_timestamp, required=True)
    eda_run.add_argument("--end", type=audit_timestamp, required=True)
    eda_run.add_argument("--phase4-artifact", type=Path, required=True)
    eda_run.add_argument("--config", type=Path, default=Path("configs/study.json"))
    eda_run.add_argument("--output-dir", type=Path, required=True, help="NEW output directory; parent must exist")
    eda_replay = eda_actions.add_parser("replay")
    eda_replay.add_argument("--bundle", type=Path, required=True, help="Existing Phase 5 EDA bundle JSON")
    eda_replay.add_argument("--output-dir", type=Path, required=True, help="NEW output directory; parent must exist")
    stats = commands.add_parser("stats", help="Phase 6 pre-registered statistics from the frozen Phase 5 bundle")
    stats_actions = stats.add_subparsers(dest="stats_action", required=True)
    stats_run = stats_actions.add_parser("run")
    stats_run.add_argument("--bundle", type=Path, required=True, help="Phase 5 EDA bundle JSON")
    stats_run.add_argument("--phase4-artifact", type=Path,
                           default=Path("docs/verification/phase_4_quality_2026-09-07_final.json"))
    stats_run.add_argument("--output-dir", type=Path, required=True, help="NEW output directory; parent must exist")
    stats_replay = stats_actions.add_parser("replay")
    stats_replay.add_argument("--bundle", type=Path, required=True, help="Phase 5 EDA bundle JSON")
    stats_replay.add_argument("--output-dir", type=Path, required=True, help="NEW output directory; parent must exist")
    baselines = commands.add_parser("baselines", help="Phase 8 reproducible chronological PM2.5 baselines")
    baseline_actions = baselines.add_subparsers(dest="baseline_action", required=True)
    baseline_run = baseline_actions.add_parser("run")
    baseline_run.add_argument("--artifact", type=Path, required=True, help="Phase 7 feature artifact directory")
    baseline_run.add_argument("--output-dir", type=Path, required=True, help="NEW Phase 8 output directory; parent must exist")
    baseline_replay = baseline_actions.add_parser("replay")
    baseline_replay.add_argument("--artifact", type=Path, required=True, help="Phase 7 feature artifact directory")
    baseline_replay.add_argument("--summary", type=Path, required=True, help="Previous Phase 8 summary JSON")
    baseline_replay.add_argument("--output-dir", type=Path, required=True, help="NEW Phase 8 output directory; parent must exist")
    ml = commands.add_parser("ml", help="Phase 9 chronological machine learning")
    ml_actions = ml.add_subparsers(dest="ml_action", required=True)
    ml_run = ml_actions.add_parser("run")
    ml_run.add_argument("--artifact", type=Path, required=True, help="Phase 7 feature artifact directory")
    ml_run.add_argument("--baseline-artifact", type=Path, required=True, help="Phase 8 v2 baseline artifact directory")
    ml_run.add_argument("--output-dir", type=Path, required=True, help="NEW Phase 9 output directory; parent must exist")
    ml_replay = ml_actions.add_parser("replay")
    ml_replay.add_argument("--artifact", type=Path, required=True, help="Phase 7 feature artifact directory")
    ml_replay.add_argument("--baseline-artifact", type=Path, required=True, help="Phase 8 v2 baseline artifact directory")
    ml_replay.add_argument("--summary", type=Path, required=True, help="Previous Phase 9 model summary JSON")
    ml_replay.add_argument("--output-dir", type=Path, required=True, help="NEW Phase 9 output directory; parent must exist")
    features = commands.add_parser("features", help="Phase 7 availability-aware feature engineering")
    feature_actions = features.add_subparsers(dest="feature_action", required=True)
    feature_extract = feature_actions.add_parser("extract")
    feature_extract.add_argument("--cutoff", type=audit_timestamp, required=True)
    feature_extract.add_argument("--start", type=audit_timestamp, required=True)
    feature_extract.add_argument("--end", type=audit_timestamp, required=True)
    feature_extract.add_argument("--config", type=Path, default=Path("configs/study.json"))
    feature_extract.add_argument("--output", type=Path, required=True, help="NEW input-bundle JSON file; parent must exist")
    feature_build = feature_actions.add_parser("build")
    feature_build.add_argument("--bundle", type=Path, required=True, help="Phase 7 input bundle JSON")
    feature_build.add_argument("--config", type=Path, required=True, help="Reviewed configuration for boundary checks")
    feature_build.add_argument("--output-dir", type=Path, required=True, help="NEW output directory; parent must exist")
    feature_build.add_argument("--horizons", type=int, nargs="+", required=True, help="Horizons in hours, subset of 6 and 24")
    feature_build.add_argument("--availability", choices=("captured", "assumed"), required=True)
    feature_build.add_argument("--assumed-lag-hours", type=float, default=None, help="Required for assumed mode; forbidden for captured")
    feature_build.add_argument("--require-frozen-boundary", action="store_true",
                               help="Require the frozen historical Phase 7 boundary instead of an explicit new window")
    feature_replay = feature_actions.add_parser("replay")
    feature_replay.add_argument("--bundle", type=Path, required=True, help="Phase 7 input bundle JSON")
    feature_replay.add_argument("--config", type=Path, required=True, help="Reviewed configuration for boundary checks")
    feature_replay.add_argument("--output-dir", type=Path, required=True, help="NEW output directory; parent must exist")
    feature_replay.add_argument("--summary", type=Path, help="Previous phase_7_feature_summary.json supplying the recorded build request")
    feature_replay.add_argument("--horizons", type=int, nargs="+")
    feature_replay.add_argument("--availability", choices=("captured", "assumed"))
    feature_replay.add_argument("--assumed-lag-hours", type=float)
    feature_replay.add_argument("--require-frozen-boundary", action="store_true",
                                help="Require the frozen historical Phase 7 boundary instead of an explicit new window")
    args = parser.parse_args()
    engine = None
    try:
        if args.command == "validate-config":
            config = load_config(args.path)
            print(f"Valid: {len(config.locations)} locations, {len(config.sensors)} sensors, {len(config.products)} products")
            return 0
        if args.command == "ingest":
            if not 1 <= args.max_requests <= 500:
                raise ValueError("max-requests must be between 1 and 500")
            if args.mode == "poll" and (args.start or args.end):
                raise ValueError("poll determines its own window; omit start/end")
            if args.mode == "backfill" and (args.start is None or args.end is None):
                raise ValueError("backfill requires start and end")
            config = load_config(args.config)
            engine = database_engine()
            worker = Ingestor(engine, config, max_requests=args.max_requests)
            try:
                results = worker.run(args.source, args.start, args.end, poll=args.mode == "poll", resume=args.resume, target_ids=args.target)
                return 0 if all(result["status"] in {"succeeded", "skipped"} for result in results) else 2
            finally:
                worker.close()
        if args.command == "report":
            from vn_air.ingestion.report import ingestion_report
            if args.output and (args.output.exists() or not args.output.parent.is_dir()):
                raise ValueError("Report output must not exist and its parent must exist")
            engine = database_engine()
            report_text = json.dumps(ingestion_report(engine), indent=2, default=str)
            if args.output:
                with args.output.open("x", encoding="utf-8") as handle:
                    handle.write(report_text + "\n")
                print(f"Report written: {args.output}")
            else:
                print(report_text)
            return 0
        if args.command == "data-quality":
            if args.quality_action == "audit":
                if args.output.exists() or not args.output.parent.is_dir():
                    raise ValueError("Audit output must not exist and its parent must exist")
                from vn_air.quality import audit_database, json_default, validate_window
                validate_window(args.cutoff, args.start, args.end)
                config = load_config(args.config)
                engine = database_engine()
                audit_report = audit_database(engine, config, cutoff=args.cutoff, start=args.start, end=args.end)
                report_text = json.dumps(audit_report, indent=2, sort_keys=True, default=json_default, allow_nan=False)
                from vn_air.quality_store import write_audit
                write_audit(args.output, report_text, engine)
                print(f"Audit written: {args.output}")
                return 0
        if args.command == "eda":
            if args.eda_action == "run":
                from vn_air.eda import run_eda
                from vn_air.quality import validate_window
                validate_window(args.cutoff, args.start, args.end)
                if args.output_dir.exists() or not args.output_dir.parent.is_dir():
                    raise ValueError("EDA output directory must be new and its parent must exist")
                if not args.phase4_artifact.is_file():
                    raise ValueError("Phase 4 artifact does not exist")
                config = load_config(args.config)
                engine = database_engine()
                result = run_eda(engine, config, cutoff=args.cutoff, start=args.start, end=args.end,
                                 phase4_artifact=args.phase4_artifact, output_dir=args.output_dir)
                print(json.dumps(result, sort_keys=True))
                return 0
            if args.eda_action == "replay":
                from vn_air.eda import replay_eda
                result = replay_eda(args.bundle, args.output_dir)
                print(json.dumps(result, sort_keys=True))
                return 0
        if args.command == "stats":
            from vn_air.statistics import bundle_file_sha256, load_bundle, run_statistics, verify_phase4_file
            from vn_air.statistics_output import write_outputs
            if args.output_dir.exists() or not args.output_dir.parent.is_dir():
                raise ValueError("Statistics output directory must be new and its parent must exist")
            if not args.bundle.is_file():
                raise ValueError("Phase 5 bundle does not exist")
            if args.stats_action == "run":
                if not args.phase4_artifact.is_file():
                    raise ValueError("Phase 4 artifact does not exist")
                bundle = load_bundle(args.bundle)
                verify_phase4_file(bundle, args.phase4_artifact)
            else:
                bundle = load_bundle(args.bundle)
            result = run_statistics(bundle, bundle_file_sha256(args.bundle))
            print(json.dumps(write_outputs(args.output_dir, result), sort_keys=True))
            return 0
        if args.command == "baselines":
            from vn_air.baselines import replay_baselines, run_baselines
            from vn_air.baselines_output import write_outputs
            if args.baseline_action == "run":
                result = run_baselines(args.artifact)
                print(json.dumps(write_outputs(args.output_dir, result), sort_keys=True))
                return 0
            print(json.dumps(replay_baselines(args.artifact, args.summary, args.output_dir), sort_keys=True))
            return 0
        if args.command == "ml":
            from vn_air.ml import replay_ml, run_ml, write_outputs
            if args.ml_action == "run":
                result = run_ml(args.artifact, args.baseline_artifact, output_dir=args.output_dir)
                print(json.dumps(write_outputs(args.output_dir, result), sort_keys=True))
                return 0
            print(json.dumps(replay_ml(args.artifact, args.baseline_artifact, args.summary,
                                       args.output_dir), sort_keys=True))
            return 0
        if args.command == "features":
            from vn_air.features import bundle_file_sha256, build_features, load_bundle
            from vn_air.features_output import write_outputs
            if args.feature_action == "extract":
                if args.output.exists() or not args.output.parent.is_dir():
                    raise ValueError("Feature bundle output must be a new file with an existing parent")
                from vn_air.features_store import extract_features
                from vn_air.quality import validate_window
                validate_window(args.cutoff, args.start, args.end)
                config = load_config(args.config)
                engine = database_engine()
                bundle = extract_features(engine, config, cutoff=args.cutoff, start=args.start, end=args.end)
                with args.output.open("x", encoding="utf-8") as handle:
                    json.dump(bundle, handle, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
                    handle.write("\n")
                print(json.dumps({"bundle": str(args.output), "bundle_sha256": bundle["bundle_sha256"],
                                  "input_counts": bundle["manifest"]["input_counts"]}, sort_keys=True))
                return 0
            if args.output_dir.exists() or not args.output_dir.parent.is_dir():
                raise ValueError("Features output directory must be new and its parent must exist")
            if not args.bundle.is_file():
                raise ValueError("Feature input bundle does not exist")
            reviewed = load_config(args.config).model_dump(mode="json")
            file_sha = bundle_file_sha256(args.bundle)
            bundle = load_bundle(args.bundle)
            if args.feature_action == "build":
                horizons, basis, lag = args.horizons, args.availability, args.assumed_lag_hours
                replay_mode = "build"
                replay_frozen = args.require_frozen_boundary
            else:
                if args.summary is not None:
                    if not args.summary.is_file():
                        raise ValueError("Feature summary does not exist")
                    request = json.loads(args.summary.read_text(encoding="utf-8"))["manifest"]
                    if request.get("bundle_sha256") != bundle["bundle_sha256"]:
                        raise ValueError("Summary-bound replay mismatch: input bundle digest differs")
                    if request.get("bundle_file_sha256") != file_sha:
                        raise ValueError("Summary-bound replay mismatch: input bundle file digest differs")
                    from vn_air.features import FEATURES_VERSION
                    if request.get("feature_version") != FEATURES_VERSION:
                        raise ValueError("Summary-bound replay mismatch: feature version differs")
                    if args.horizons and sorted(args.horizons) != sorted(request["horizons"]):
                        raise ValueError("Summary-bound replay mismatch: horizons differ")
                    if args.availability and args.availability != request["availability_basis"]:
                        raise ValueError("Summary-bound replay mismatch: availability differs")
                    if args.availability and (args.assumed_lag_hours or None) != (request.get("availability_assumption") or None):
                        raise ValueError("Summary-bound replay mismatch: assumed lag differs")
                    replay_mode = "summary_bound"
                    horizons, basis, lag = (request["horizons"], request["availability_basis"],
                                            request["availability_assumption"])
                    replay_frozen = bool(request.get("boundary", {}).get("frozen_boundary_applied"))
                elif args.horizons and args.availability:
                    replay_mode = "explicit"
                    horizons, basis, lag = args.horizons, args.availability, args.assumed_lag_hours
                    replay_frozen = args.require_frozen_boundary
                else:
                    raise ValueError("Replay requires --summary or explicit --horizons/--availability")
            result = build_features(bundle, file_sha, horizons=horizons,
                                    availability_basis=basis, assumed_lag_hours=lag,
                                    reviewed=reviewed, require_frozen_boundary=replay_frozen)
            print(json.dumps({**write_outputs(args.output_dir, result), "replay_request_mode": replay_mode},
                             sort_keys=True))
            return 0
        config = load_config(args.config) if args.action == "seed" else None
        engine = database_engine()
        with engine.begin() as connection:
            if args.action == "upgrade":
                migrate(connection)
                print("Database schema upgraded to head")
            elif args.action == "seed":
                assert config is not None
                print(json.dumps(seed_reference_data(connection, config), sort_keys=True))
            else:
                installed = connection.execute(text("SELECT to_regclass('public.vn_air_schema_version')")).scalar_one()
                if installed is None:
                    print("Database is not migrated")
                    return 1
                revision = connection.execute(text("SELECT version_num FROM public.vn_air_schema_version")).scalar_one_or_none()
                print(f"Schema revision: {revision or 'base'}")
        return 0
    except ValidationError as error:
        print(f"Invalid configuration: {error.error_count()} validation error(s); inspect the documented schema", file=sys.stderr)
    except IngestionError as error:
        print(f"Ingestion stopped: {error.code}", file=sys.stderr)
    except (ValueError, OSError) as error:
        print("Audit failed: invalid input, extraction or output; no source data changed" if args.command == "data-quality" else str(error), file=sys.stderr)
    except SQLAlchemyError as error:
        sqlstate = getattr(getattr(error, "orig", None), "sqlstate", None)
        print(f"Database operation failed ({sqlstate or type(error).__name__}); check connection, schema and permissions", file=sys.stderr)
    except Exception:
        if args.command != "data-quality":
            raise
        print("Audit failed: unexpected error; no source data changed", file=sys.stderr)
    finally:
        if engine is not None:
            engine.dispose()
    return 1


if __name__ == "__main__":
    sys.exit(main())
