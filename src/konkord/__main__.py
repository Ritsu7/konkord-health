import argparse
import json
import os
import sys
from pathlib import Path
from .adapters.hl7v2 import parse_hl7_oru
from .adapters.fhir import load_fhir_bundle
from .reconciliation import compare_many


def _apply_db_url(args) -> None:
    """Override KONKORD_DATABASE_URL for this process if --postgres-connection-string was passed.

    Must run before the first `from .db import ...`, since `db.session`
    reads the env var once, at import time, into a module-level engine.
    """
    if getattr(args, "postgres_connection_string", None):
        os.environ["KONKORD_DATABASE_URL"] = args.postgres_connection_string


def _run_compare(args) -> int:
    try:
        source = parse_hl7_oru(Path(args.source).read_text(encoding="utf-8"))
        target = load_fhir_bundle(args.target)
        report = compare_many(source, target)
        output = json.dumps(report, indent=2)
        if args.report:
            Path(args.report).write_text(output + "\n", encoding="utf-8")

        job_id = None
        if args.save:
            _apply_db_url(args)
            try:
                from .db import init_db, save_job_report, SessionLocal
            except ImportError:
                print(
                    "error: --save requires persistence; run `pip install -e \".[db]\"` "
                    "to enable it (backed by KONKORD_DATABASE_URL, or a local "
                    "sqlite:///./konkord.db by default)",
                    file=sys.stderr,
                )
                return 2
            init_db()
            db = SessionLocal()
            try:
                job = save_job_report(db, report, correlation_id=args.correlation_id)
                job_id = job.id
            finally:
                db.close()

        print(output)
        if job_id:
            print(f"Saved as job_id={job_id} (check with: konkord status --job-id {job_id})", file=sys.stderr)
        return 1 if report["overall"] == "FAIL" else 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _run_jobs(args) -> int:
    _apply_db_url(args)
    try:
        from .db import init_db, list_jobs, SessionLocal
    except ImportError:
        print(
            "error: persistence not installed; run `pip install -e \".[db]\"` "
            "to enable job history (backed by KONKORD_DATABASE_URL, or a "
            "local sqlite:///./konkord.db by default)",
            file=sys.stderr,
        )
        return 2
    init_db()
    db = SessionLocal()
    try:
        jobs = list_jobs(db, limit=args.limit)
        rows = [
            {
                "job_id": j.id,
                "created_at": j.created_at.isoformat(),
                "overall": j.overall,
                "correlation_id": j.correlation_id,
            }
            for j in jobs
        ]
    finally:
        db.close()
    print(json.dumps(rows, indent=2))
    return 0


def _run_status(args) -> int:
    _apply_db_url(args)
    try:
        from .db import init_db, get_job, SessionLocal
        from .db.repository import job_to_report
    except ImportError:
        print(
            "error: `status` requires persistence; run `pip install -e \".[db]\"` "
            "to enable it (backed by KONKORD_DATABASE_URL, or a local "
            "sqlite:///./konkord.db by default)",
            file=sys.stderr,
        )
        return 2
    init_db()
    db = SessionLocal()
    try:
        job = get_job(db, args.job_id)
        if job is None:
            print(f"error: no job found with id {args.job_id}", file=sys.stderr)
            return 2
        report = job_to_report(job)
    finally:
        db.close()

    issues = [c for c in report["checks"] if c["status"] in ("FAIL", "WARN")]
    print(f"job_id:         {report['job_id']}")
    print(f"created_at:     {report['created_at']}")
    print(f"correlation_id: {report.get('correlation_id')}")
    print(f"overall:        {report['overall']}")
    if issues:
        print(f"\nissues found ({len(issues)}):")
        print(json.dumps(issues, indent=2))
    else:
        print("\nno issues found (all checks PASS/INDETERMINATE)")
    return 1 if report["overall"] == "FAIL" else 0


def main():
    parser = argparse.ArgumentParser(prog="konkord", description="Konkord: healthcare source-to-target data assurance")
    sub = parser.add_subparsers(dest="command", required=True)

    cmp = sub.add_parser("compare", help="Compare HL7 ORU observations to a FHIR Bundle/Observation")
    cmp.add_argument("--source", required=True)
    cmp.add_argument("--target", required=True)
    cmp.add_argument("--report")
    cmp.add_argument(
        "--save", action="store_true",
        help="Persist this report as a job (requires the `db` extra); without this flag no database is touched",
    )
    cmp.add_argument("--correlation-id", help="Optional correlation id to tag the saved job with (only used with --save)")
    cmp.add_argument(
        "--postgres-connection-string",
        help="PostgreSQL connection string to persist to (only used with --save), e.g. "
        "postgresql+psycopg://user:pass@host:5432/dbname. Overrides KONKORD_DATABASE_URL "
        "for this run; defaults to sqlite:///./konkord.db if neither is set.",
    )

    jobs = sub.add_parser("jobs", help="List recently persisted reconciliation jobs (requires the `db` extra)")
    jobs.add_argument("--limit", type=int, default=50)
    jobs.add_argument(
        "--postgres-connection-string",
        help="PostgreSQL connection string to read from, e.g. postgresql+psycopg://user:pass@host:5432/dbname. "
        "Overrides KONKORD_DATABASE_URL for this run; defaults to sqlite:///./konkord.db if neither is set.",
    )

    status = sub.add_parser("status", help="Show a persisted job's status and any issues found (requires the `db` extra)")
    status.add_argument("--job-id", required=True)
    status.add_argument(
        "--postgres-connection-string",
        help="PostgreSQL connection string to read from, e.g. postgresql+psycopg://user:pass@host:5432/dbname. "
        "Overrides KONKORD_DATABASE_URL for this run; defaults to sqlite:///./konkord.db if neither is set.",
    )

    args = parser.parse_args()
    if args.command == "compare":
        return _run_compare(args)
    if args.command == "jobs":
        return _run_jobs(args)
    return _run_status(args)

if __name__ == "__main__":
    sys.exit(main())
