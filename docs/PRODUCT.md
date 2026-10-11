# Product specification

## Mission

Continuously verify that healthcare data retains intended meaning, identity, relationships and usability as it moves across systems (HL7v2 → FHIR, FHIR → FHIR, and migration/drift between two FHIR snapshots).

## Target users

Healthcare integration engineers; EHR/FHIR implementation teams; payer interoperability teams; migration delivery teams; data quality and compliance teams.

## Capabilities implemented today

1. **Preservation** — source/target field and concept comparison across 20 clinical/administrative domains (Laboratory, Identity, Encounter, Medication, Allergy, Condition, Procedure, Coverage, Prior Authorization, Claims, Terminology, Documents, Provider Directory, Member Attribution, Formulary, CarePlan, ServiceRequest, Immunization, Goal, CareTeam, Risk Adjustment, CDex, DiagnosticReport).
2. **Consistency** — identity, patient/encounter reference, and cross-record checks (missing, duplicate, and inconsistent-reference detection) in every `compare_many_*()` path.
3. **Reconciliation** — bulk migration batch comparison and export-run-history drift detection (`reconciliation.engine.compare_fhir_resource_batches`, `compare_export_run_history`).
4. **Evidence** — every comparison produces a structured report (`PASS`/`FAIL`/`WARN`/`INDETERMINATE` findings) via the CLI, direct library calls, or as a persisted job (optional Postgres/SQLite backing).
5. **Historical-baseline drift detection** — `reconciliation.engine.compare_run_history()` is domain-agnostic (works on the report from any `compare*()` function, not just migration) and checks sync-gap, contract-compliance-rate drop, and per-rule field-population-distribution shift against a run history (SC-116/117/119/120). When the `db` extra is installed, callers can pass `correlation_id` and look up that pipeline's prior persisted runs via `db.repository.list_jobs_by_correlation()` to feed `compare_run_history()` themselves — no server round-trip required.
6. **Opt-in alerting** — `konkord.alerting.send_alert()` optionally POSTs a non-PHI signal (`overall`, per-status counts, `correlation_id`, `job_id` — never `checks`/field values) to a webhook. The caller invokes it explicitly after a `compare*()` call; it is not triggered automatically. Disabled unless `KONKORD_ALERT_WEBHOOK_URL` is set; fires only for `FAIL`/`WARN` runs by default (configurable via `KONKORD_ALERT_ON`). Delivery failures are logged and never raise.

See `docs/scenario-registry.csv` for the full, per-scenario breakdown (173 scenarios tracked, 166 `IMPLEMENTED`) and `docs/ARCHITECTURE.md` for how a comparison runs end to end.

## Capabilities explicitly not implemented (see "Not in scope" below)

Standards/profile conformance validation (delegate to the FHIR Validator/Inferno), fuzzy/probabilistic record linkage, and a full analytics/hosted dashboard product (charts, trend visualizations, multi-tenant UI). Historical-baseline drift detection and basic webhook alerting exist (see items 5-6 above); what's not implemented is anything beyond that: no built-in alert-routing/escalation policies (PagerDuty/Slack-specific integrations, dedup, quiet hours), and no long-running monitoring process — alerting is a synchronous, best-effort call the caller makes explicitly, not an independent scheduler. There is no built-in UI or server; job history is only accessible by querying the optional database directly (`konkord jobs`/`konkord status` CLI commands, or `db.repository` calls).

## Product surfaces

Local CLI (`konkord compare`, `konkord jobs`, `konkord status`), and direct Python import of `konkord.reconciliation`/`konkord.engine` for use in scripts or notebooks (e.g. Databricks). Optional Postgres/SQLite job persistence (`db` extra) and opt-in webhook alerting (`konkord.alerting`). Findings are a plain Python dict or JSON file, meant to be consumed by CI, scripts, notebooks, or a separate internal tool.

## Commercial direction

Open-source core (adapters, rule packs, reconciliation engine, CLI). Commercial options to evaluate later: managed/hosted deployment, large-scale/batch processing support, a full analytics/visualization dashboard, and enterprise support — none of these exist today; this is a direction to validate, not a committed roadmap.

## Not in scope

Clinical decision making, automatic remediation of patient records, EHR replacement, acting as a FHIR repository/server, real patient data in public demos or fixtures, unsupported assertions of HIPAA certification or regulatory compliance, standards/profile conformance validation (use the official FHIR Validator or Inferno alongside Konkord), and fuzzy/probabilistic patient or record matching (all matching is by an explicit domain key).

## Differentiation to validate

Independent, evidence-backed source-to-target semantic reconciliation across a broad set of US Core and Da Vinci IG domains, with explicit PASS/FAIL/WARN/INDETERMINATE evidence per field. Compare against HL7 Validator, Inferno, CumulusQ, PIQI-related work and integration vendors before claiming uniqueness.
