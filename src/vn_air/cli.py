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
