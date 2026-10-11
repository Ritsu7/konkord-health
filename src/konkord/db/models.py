"""SQLAlchemy ORM models for assurance jobs and their findings.

A "job" is one `/v1/assurance/compare` invocation; it owns an ordered list
of findings (one row per rule check), mirroring `evidence.report.build_report`.
"""
from __future__ import annotations
import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _new_job_id() -> str:
    return str(uuid.uuid4())


class Job(Base):
    __tablename__ = "assurance_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_job_id)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )
    schema_version: Mapped[str] = mapped_column(String(32))
    overall: Mapped[str] = mapped_column(String(16))
    disclaimer: Mapped[str] = mapped_column(Text)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    findings: Mapped[list["Finding"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="Finding.sequence"
    )


class Finding(Base):
    __tablename__ = "assurance_findings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("assurance_jobs.id", ondelete="CASCADE"))
    sequence: Mapped[int] = mapped_column()
    rule_id: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16))
    source_value: Mapped[str] = mapped_column(Text)
    target_value: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text)

    job: Mapped[Job] = relationship(back_populates="findings")
