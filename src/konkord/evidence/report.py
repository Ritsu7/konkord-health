"""Structured, minimal evidence reports.

No patient identifiers or full payloads are included by default; values
compared may still be sensitive, so callers running on real PHI must
apply their own minimization/redaction policy before export.
"""
from __future__ import annotations

SCHEMA_VERSION = "0.2.0"
DISCLAIMER = "Prototype; synthetic test data only; not a complete conformance or clinical validation tool."


def overall_status(statuses: list) -> str:
    if "FAIL" in statuses:
        return "FAIL"
    if statuses and all(s == "INDETERMINATE" for s in statuses):
        return "INDETERMINATE"
    if "WARN" in statuses:
        return "WARN"
    if "INDETERMINATE" in statuses:
        return "INDETERMINATE"
    return "PASS"


def build_report(findings: list) -> dict:
    statuses = [f["status"] for f in findings]
    return {
        "schema_version": SCHEMA_VERSION,
        "overall": overall_status(statuses),
        "checks": findings,
        "disclaimer": DISCLAIMER,
    }
