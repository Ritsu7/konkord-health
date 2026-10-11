# Architecture

This document describes the architecture and data-flow workflow of
Konkord **as implemented** in `src/konkord/`, not an aspirational target
state. Every module named below exists in the codebase; see
`CONTRIBUTING.md` for the file-to-module map and `docs/scenario-registry.csv`
for the full list of checks each rule pack implements.

## Data-flow workflow

```text
       Source snapshot                      Target snapshot
   (HL7v2 message, or FHIR          (FHIR R4B Bundle / resource,
   Bundle for FHIR-to-FHIR              JSON file or dict)
          domains)
              |                                |
              v                                v
       adapters.hl7v2                    adapters.fhir
   (segment/field parsing)         (fhir.resources R4B model
              |                            validation)
              |                                |
              +----------------+---------------+
                               |
                               v
                     reconciliation.engine
              (compare / compare_many / compare_many_*)
         - matches source records to target resources by
           domain-appropriate key (LOINC code, order code,
                   allergen code, NPI, etc.)
         - detects missing records, duplicate records, and
             inconsistent patient/encounter references
                               |
                               v
                        rules.registry
     (per-domain rule packs: lab, identity, encounter, medication,
      allergy, condition, procedure, coverage, priorauth, claim,
       provider, terminology, document, immunization, goal,
              careteam, detectedissue, task, diagnosticreport, ...)
      each rule is a pure function returning a finding with status
                 PASS | WARN | FAIL | INDETERMINATE
                               |
                               v
                        evidence.report
       (aggregates per-record/per-field findings into one
         report: overall status, list of findings, counts)
                               |
                 +-------------+-------------+
                 v                           v
           __main__ (CLI)               db.repository
      exits 0/1, writes               (optional; persists jobs
      report.json or returns          to Postgres/SQLite via
      a dict when called as           SQLAlchemy, migrated with
         a library function                 Alembic)
```

All processing is synchronous, in-process, and stateless by default (the
DB layer is opt-in via the `db` extra). There is no server, queue, or
background worker — Konkord is a library: call `konkord.engine.compare()`
(or the other `compare*()` functions) directly from a script or notebook,
or run the bundled `konkord` CLI. There is no built-in UI or REST surface;
findings are a plain Python dict (or JSON via the CLI's `--report` file),
meant to be consumed by whatever the caller plugs in next (a notebook cell,
CI pipeline, ticketing system, etc.). Konkord makes no outbound network
calls; the optional `alerting.send_alert()` helper is available for callers
who want to POST a non-PHI summary to their own webhook, but it is not
wired into the CLI or engine automatically — the caller invokes it
explicitly.

## Modules (`src/konkord/`)

- `adapters/hl7v2.py`: segment/field parsers for each supported HL7v2
  message type (ORU, RDE, VXU, ADT-derived segments), returning plain
  dicts/lists with provenance-preserving raw field values.
- `adapters/fhir.py`: FHIR R4B Bundle/resource loading and parsing via the
  `fhir.resources` library, one `parse_fhir_<domain>_bundle()` /
  `load_fhir_<domain>_bundle()` pair per domain.
- `rules/`: one module per domain (`lab_observation.py`,
  `identity_observation.py`, `encounter_observation.py`,
  `medication_observation.py`, `allergy_observation.py`,
  `condition_observation.py`, `procedure_observation.py`,
  `coverage_observation.py`, `priorauth_observation.py`,
  `claim_observation.py`, `provider_observation.py`,
  `terminology_observation.py`, `document_observation.py`,
  `immunization_observation.py`, `diagnosticreport_observation.py`, ...),
  each exporting pure, deterministic rule functions registered in
  `rules/registry.py`.
- `reconciliation/engine.py`: the comparison engine — `compare()` /
  `compare_many()` for the original lab/identity/encounter path, plus one
  `compare_many_<domain>()` per additional domain (medication, allergy,
  condition, procedure, coverage, priorauth, claim, document,
  provider_directory, member_attribution, migration batch/run-history,
  formulary, careplan, servicerequest, immunization, goal, careteam,
  detected_issues, tasks, diagnosticreports).
- `evidence/report.py`: builds the final report dict (`overall`,
  `findings`, counts by status) from the raw list of per-rule findings.
- `engine.py`: backward-compatible re-export shim over the modules above,
  so existing imports of `konkord.engine.compare_many` keep working.
- `db/`: SQLAlchemy models (`models.py`), session/engine setup
  (`session.py`), and job persistence (`repository.py`, including
  `list_jobs_by_correlation()` for server-side run-history lookup);
  optional, behind the `db` extra; `alembic/` holds schema migrations.
- `alerting.py`: optional, off-by-default webhook notification
  (`send_alert()`) posting only a non-PHI signal — `overall`, per-status
  counts, `correlation_id`, `job_id` — never `checks`/field values; no-op
  unless `KONKORD_ALERT_WEBHOOK_URL` is set.
- `__main__.py`: the CLI entry point — `konkord compare` (with optional
  `--save`/`--correlation-id`/`--postgres-connection-string` persistence),
  `konkord jobs` (list persisted runs), `konkord status` (inspect one
  persisted run's findings); the latter two require the `db` extra.

## Design requirements actually enforced in the code

1. Every rule function is deterministic and pure — same inputs always
   produce the same finding; no network calls, no wall-clock dependence.
2. Findings use four statuses: `PASS`, `FAIL`, `WARN`, `INDETERMINATE`
   (used when the source format has no field to compare against, e.g. a
   missing optional HL7v2 Z-segment) — never silently inferred equivalence.
3. `compare_many*()` functions always distinguish *missing* (present in
   source, absent in target), *duplicate* (multiple target records with
   the same match key), and *mismatched* (matched but a field differs)
   outcomes, rather than collapsing them into one failure type.
4. Matching is by an explicit domain key (LOINC code, RxNorm-style
   ingredient code, allergen code, NPI, resource `id`, etc.) — there is no
   fuzzy/probabilistic record linkage.
5. No outbound network calls or telemetry by default. The only exception is
   the opt-in `alerting.send_alert()` helper, which a caller may invoke
   explicitly; it only ever sends aggregate counts/identifiers, never field
   values, and only when the caller passes a webhook URL.
6. All example fixtures under `examples/` are synthetic; `docs/SECURITY.md`
   documents the PHI-handling expectations for real usage.

## Explicitly out of scope

Conformance/profile validation (delegate to the official FHIR Validator or
Inferno — Konkord only diffs two already-structurally-valid snapshots),
record linkage/MPI (fuzzy patient matching), clinical decision support,
automatic remediation of records, and a full hosted analytics dashboard
(charts, trend visualizations, multi-tenant UI) — Konkord has no built-in UI;
job history is JSON only. Alert
routing/escalation (PagerDuty/Slack-specific integrations, deduplication,
quiet hours) and a long-running monitoring scheduler are also out of
scope — `alerting.send_alert()` is a synchronous, best-effort webhook POST
fired as a side effect of a `compare` call, not an independent service.
These are product decisions documented in `docs/PRODUCT.md`, not
implementation gaps to be filled by this codebase.
