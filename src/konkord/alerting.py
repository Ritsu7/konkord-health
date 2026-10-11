"""Opt-in, egress-off-by-default alerting for reconciliation findings.

Konkord is a stateless/offline diff engine by default: PHI-bearing field
values (`source_value`/`target_value`) never leave the process unless the
caller explicitly asks for them in the API/CLI response. This module adds an
*optional* outbound webhook notification for a run's result, but it only
ever sends a non-PHI signal -- `overall`, per-status counts, the
caller-supplied `correlation_id`, and `job_id`/`timestamp` if present. It
never sends `checks` (no `rule_id`/`source_value`/`target_value`/
`explanation` content).

Disabled unless a webhook URL is explicitly configured (via the
`webhook_url` argument or the `KONKORD_ALERT_WEBHOOK_URL` environment
variable), so no network egress happens unless an operator opts in.
"""
from __future__ import annotations
import json
import logging
import os
import urllib.error
import urllib.request
from collections import Counter

logger = logging.getLogger("konkord.alerting")

# Only alert on runs that need attention by default; a pure PASS run is not
# POSTed anywhere unless the operator widens this list.
DEFAULT_ALERT_STATUSES = ("FAIL", "WARN")


def _configured_webhook_url(webhook_url: str | None) -> str | None:
    return webhook_url if webhook_url is not None else os.environ.get("KONKORD_ALERT_WEBHOOK_URL")


def _configured_alert_statuses(alert_on: list[str] | None) -> set[str]:
    if alert_on is not None:
        return {s.strip().upper() for s in alert_on if s.strip()}
    env_value = os.environ.get("KONKORD_ALERT_ON")
    if env_value:
        return {s.strip().upper() for s in env_value.split(",") if s.strip()}
    return set(DEFAULT_ALERT_STATUSES)


def build_alert_payload(report: dict) -> dict:
    """Build the non-PHI alert payload for a report returned by any
    `compare*()`/`compare_run_history()` function (or the API response dict).

    Deliberately omits `checks` entirely: only aggregate counts and
    identifiers that the caller themselves supplied (`correlation_id`) or
    that Konkord generated as an opaque id (`job_id`), never field values.
    """
    statuses = [c.get("status") for c in report.get("checks", [])]
    counts = Counter(statuses)
    return {
        "overall": report.get("overall"),
        "counts": {status: counts.get(status, 0) for status in ("PASS", "WARN", "FAIL", "INDETERMINATE")},
        "total_checks": len(statuses),
        "correlation_id": report.get("correlation_id"),
        "job_id": report.get("job_id"),
        "created_at": report.get("created_at"),
    }


def send_alert(report: dict, webhook_url: str | None = None, alert_on: list[str] | None = None,
                timeout: float = 5.0) -> bool:
    """POST the non-PHI alert payload for `report` to the configured webhook,
    if one is configured and `report["overall"]` is in the alert-worthy set.

    Returns True if an alert was sent, False if alerting is disabled (no
    webhook configured) or this report's `overall` doesn't warrant one.
    Network/HTTP errors are logged and swallowed -- a notification failure
    must never fail or block the reconciliation request itself.
    """
    url = _configured_webhook_url(webhook_url)
    if not url:
        return False

    overall = report.get("overall")
    if overall not in _configured_alert_statuses(alert_on):
        return False

    payload = build_alert_payload(report)
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout):
            pass
    except (urllib.error.URLError, OSError) as exc:
        logger.warning("alert webhook delivery failed", extra={"webhook_error": str(exc)})
        return False
    return True
