"""Read/write helpers for assurance jobs and findings.

Kept free of FastAPI/Pydantic imports so it can be reused by the CLI,
background workers, or tests without pulling in the web framework.
"""
from __future__ import annotations
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Finding, Job


def save_job_report(db: Session, report: dict, correlation_id: Optional[str] = None) -> Job:
    """Persist one reconciliation report (as returned by evidence.build_report)
    as a Job with ordered Finding rows. Returns the persisted Job.
    """
    job = Job(
        schema_version=report["schema_version"],
        overall=report["overall"],
        disclaimer=report["disclaimer"],
        correlation_id=correlation_id,
    )
    for i, check in enumerate(report["checks"]):
        job.findings.append(
            Finding(
                sequence=i,
                rule_id=check["rule_id"],
                status=check["status"],
                source_value=check["source_value"],
                target_value=check["target_value"],
                explanation=check["explanation"],
            )
        )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_job(db: Session, job_id: str) -> Optional[Job]:
    return db.get(Job, job_id)


def list_jobs(db: Session, limit: int = 50) -> list[Job]:
    stmt = select(Job).order_by(Job.created_at.desc()).limit(limit)
    return list(db.scalars(stmt))


def list_jobs_by_correlation(db: Session, correlation_id: str, limit: int = 50,
                              before_job_id: Optional[str] = None) -> list[Job]:
    """Fetch prior jobs for the same pipeline (same `correlation_id`),
    oldest-first, so they can be fed as `history` into
    `reconciliation.engine.compare_run_history()` without the caller ever
    re-submitting old bundles -- the server already has every prior run's
    report persisted, keyed by the caller-supplied `correlation_id`.

    before_job_id: if given, excludes that job itself (typically the job
    just created for the current run) from the returned history so a job
    is never compared against its own report.
    """
    stmt = select(Job).where(Job.correlation_id == correlation_id)
    if before_job_id is not None:
        stmt = stmt.where(Job.id != before_job_id)
    stmt = stmt.order_by(Job.created_at.asc()).limit(limit)
    return list(db.scalars(stmt))


def job_to_report(job: Job) -> dict:
    """Convert a persisted Job (+ Findings) back into the report dict shape
    used by the API response models.
    """
    return {
        "schema_version": job.schema_version,
        "overall": job.overall,
        "checks": [
            {
                "rule_id": f.rule_id,
                "status": f.status,
                "source_value": f.source_value,
                "target_value": f.target_value,
                "explanation": f.explanation,
            }
            for f in job.findings
        ],
        "disclaimer": job.disclaimer,
        "correlation_id": job.correlation_id,
        "job_id": job.id,
        "created_at": job.created_at.isoformat(),
    }
