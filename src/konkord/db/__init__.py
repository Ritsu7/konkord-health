"""Persistence layer for the Konkord API: job/findings storage.

Backed by PostgreSQL in production (via `KONKORD_DATABASE_URL`), SQLite by
default for local development/tests. Requires the optional `db` extra:
`pip install -e ".[db]"`.
"""
from .session import get_session, init_db, SessionLocal  # noqa: F401
from .repository import save_job_report, get_job, list_jobs, list_jobs_by_correlation, job_to_report  # noqa: F401
