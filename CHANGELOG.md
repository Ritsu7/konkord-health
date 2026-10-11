# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Production hardening: a global exception handler now catches any unhandled
  error in the API, logs it via the structured JSON logger, and returns a
  consistent `500 {"detail": "internal server error"}` instead of leaking a
  raw traceback. Request-validation errors (malformed bodies) are normalized
  to the same `{"detail": ...}` shape. `POST /v1/assurance/compare/upload`
  now enforces a configurable per-file size cap (`KONKORD_MAX_UPLOAD_BYTES`,
  default 10 MiB), rejecting oversized uploads with `413` before decoding.
  The Helm chart exposes this as `api.maxUploadBytes`.

### Fixed
- Validated the Helm chart end-to-end against local minikube (lint, template,
  image build, install, live `/healthz` + `/metrics` checks). This caught a
  real deployment bug: `api.maxUploadBytes` was rendered by Helm's `quote`
  filter in scientific notation (e.g. `1.048576e+07`), which crashed the API
  container at import. Fixed by quoting the value as a string in
  `values.yaml` and hardening `KONKORD_MAX_UPLOAD_BYTES` parsing to also
  accept a float-formatted string.

### Added

- **Cross-record identity-matching group** (SC-011, SC-015, SC-024, SC-047,
  SC-049): five scenarios reclassified `PLANNED` -> `IMPLEMENTED` by adding
  cross-record checks to `compare_batch()` and `compare_many_allergies()`.
  `IDENTITY.WRONG_PATIENT_ASSIGNMENT` (SC-011) detects a target Patient whose
  demographic identity (family name + birth date) doesn't match its
  MRN-matched source patient but matches a *different* source patient in the
  batch. `IDENTITY.SPLIT` (SC-015) detects a source patient's demographic
  identity appearing on more than one distinct target Patient resource.
  `ENCOUNTER.WRONG_PATIENT_ASSIGNMENT` (SC-024) detects a matched target
  Patient's Encounter carrying a visit-number identifier that belongs to a
  different source patient in the batch. `ALLERGY.NO_KNOWN_ALLERGY_ASSERTION`
  (SC-047) detects a "no known allergies" sentinel (SNOMED
  716186003/160244002, or site-defined "NKA"/"NO KNOWN ALLERGIES") on one
  side contradicted by real allergen entries on the other.
  `ALLERGY[code].REACTION_LINKED_TO_WRONG_SUBSTANCE` (SC-049) detects a
  source allergy's reaction manifestation(s) missing from its matched target
  AllergyIntolerance but present on a *different* target AllergyIntolerance
  in the same bundle.
- **Provenance content check** (SC-115): `RECORD[key].PROVENANCE` in
  `compare_migration_batch()` compares a matched Provenance resource's
  agent/activity/entity content across migration, independent of SC-114's
  meta.source lineage-presence check.
- **Prior Authorization extension-based fields** (SC-073, SC-076): since
  base FHIR R4B `ClaimResponse.item` has no native `productOrService`
  element and `ClaimResponse` has no `supportingInfo` echo, both are now
  carried as extensions (the same pattern used elsewhere for
  Formulary/ATR data) and checked in `compare_many_prior_authorizations()`
  via `PRIORAUTH[id].ITEM[seq].SERVICE_CODE` and
  `PRIORAUTH[id].SUPPORTING_INFO`. Registry now 166/173 `IMPLEMENTED`; the
  remaining 7 `PLANNED` scenarios require either new HL7v2 message-type
  support (ADT trigger events, MRG segment) or have no analog at all on the
  source side (e.g. `EOB.payment` is purely payer-adjudication data).
- **Pluggable terminology backend** (`konkord/rules/terminology_provider.py`):
  introduces a `TerminologyProvider` protocol with a `BundledTerminologyProvider`
  default (preserves the previous hardcoded tables) and a `JSONTerminologyProvider`
  that loads/merges overrides from a file referenced by the
  `KONKORD_TERMINOLOGY_CONFIG` environment variable. A new
  `set_terminology_provider()` lets callers install a custom provider directly
  (e.g. backed by a real FHIR terminology server). All `TERMINOLOGY.*` rules in
  `terminology_observation.py` now resolve code systems, local mappings,
  ValueSet bindings, UCUM conversions, deprecations, and SNOMED parent/child
  relationships through `get_terminology_provider()` instead of module-level
  dicts. Covered by new `TerminologyProviderOverrideTests` in
  `tests/test_engine.py`. Also fixes a `ResourceWarning` from an unclosed file
  handle when loading JSON terminology configs.
- **Two new Laboratory rules** closing US Core Laboratory Result Observation
  Must Support gaps (SC-171, SC-172): `LAB.METHOD` (OBX-17 Observation
  Method vs `Observation.method.coding[].code`) and `LAB.PERFORMER` (OBX-16
  Responsible Observer vs `Observation.performer[].reference`, substring
  match). `adapters/hl7v2.py`'s `_parse_obx_fields` now captures both OBX-16
  and OBX-17.
- **One new DiagnosticReport rule** closing a US Core Laboratory Result
  Diagnostic Report Must Support gap (SC-173): `DIAGNOSTICREPORT.PERFORMER`
  (OBR-32 Principal Result Interpreter vs
  `DiagnosticReport.performer[].reference`, substring match).
  `adapters/hl7v2.py`'s `_parse_obr_report_fields` now captures OBR-32.
- **NDJSON target ingestion** (`*.ndjson`/`*.ndjsonl`): `ndjson_to_bundle()`
  in `konkord/adapters/fhir.py` parses newline-delimited FHIR resources (one
  resource per line, no `Bundle` wrapper required — the format used by FHIR
  Bulk Data exports) into an in-memory `collection` Bundle. All target
  loaders (CLI `--target`, `POST /v1/assurance/compare/upload`'s
  `target_file`) now detect `.ndjson`/`.ndjsonl` by filename extension and
  route through this parser transparently; a malformed line raises `422`
  naming the 1-based line number.
- **`GET /docs/ingest`** — a detailed, static, server-rendered data
  ingestion reference page (no JS, no new dependency) modelled on the
  Firely Server ingestion docs: supported source/target formats, NDJSON
  ingestion, all four ingestion methods (CLI, REST JSON body, REST file
  upload, dashboard upload form), correlation/trend detection, and error
  handling. Linked from the dashboard header, README, and
  `docs/USER-GUIDE.md`.
- **`GET /`** — a product homepage, separate from `/dashboard` and
  `/docs/ingest`: explains what Konkord does, with a click-to-explore
  interactive architecture diagram (adapters, rule packs, reconciliation
  engine, evidence/report builder, REST API, persistence) and an animated,
  clickable/"Play"-able data-flow diagram walking a comparison end to end
  (source in → parse → target in → parse → match → compare → build report →
  persist → alert). Plain HTML/CSS/vanilla JS, no framework, no new
  dependency.
- `test_compare_upload_endpoint_accepts_ndjson_target` /
  `..._rejects_invalid_ndjson_target` / `test_ingest_docs_page_serves_static_html` /
  `test_homepage_serves_interactive_website`
  added to `tests/test_engine.py` (164 tests passing).

### Changed

- `docs/ARCHITECTURE.md` and `docs/PRODUCT.md` rewritten to describe the
  system **as implemented** rather than an aspirational target state: the
  architecture doc now documents the real module list
  (`adapters`/`rules`/`reconciliation`/`evidence`/`api`/`db`), the actual
  data-flow workflow from source/target snapshot to report, and the
  implemented REST surface, in place of the old unbuilt module list
  (`canonical`, `matching`, `validation`, `terminology`, `contracts`,
  `monitoring`) and "target public API (not implemented)" section. The
  product doc drops the never-built "web dashboard" / "enterprise
  governance" product surfaces and states explicitly that no UI/dashboard
  exists today — findings are JSON only, consumed by the CLI, REST API, or
  a separate system. `docs/SCENARIOS.md` updated from "120 proposed checks,
  not implemented" to the current 173-scenario / 158-`IMPLEMENTED` count.
- `docs/ROADMAP.md` removed: its "first 10 working days" and "delivery
  gates" milestones were long superseded by the 155-scenario, 20-domain
  implementation now in `docs/scenario-registry.csv`, and its one
  still-relevant note (the Provider Directory/ATR/Formulary `PLANNED`
  domains) is already tracked in the registry itself.

### Added

- **`POST /v1/assurance/compare/upload`**: file-upload counterpart to
  `POST /v1/assurance/compare`, accepting `multipart/form-data`
  (`source_file` + `target_file`, plus `correlation_id`/`include_trend`
  form fields) instead of a JSON body, running through the identical
  `_run_compare()` reconciliation/persistence/trend/alerting pipeline.
  Lets a human (or a caller that already has real HL7v2/FHIR files on
  disk) submit them directly instead of hand-building JSON. Requires the
  new `python-multipart` dependency (pulled in by the `api` extra). The
  dashboard's new "Run a comparison" card wraps this endpoint with a file
  picker. The existing JSON `POST /v1/assurance/compare` remains the
  integration point for programmatic callers (upstream systems that
  already hold the data in memory).
- **Dedicated Kubernetes namespace** for Konkord: `helm/konkord/templates/namespace.yaml`
  (opt-in via `namespace.create`, off by default — install with
  `helm install konkord helm/konkord --namespace konkord --create-namespace`
  for the standard flow, or set `namespace.create=true` for GitOps/ArgoCD
  flows that apply rendered manifests directly without `helm install`).
- **Interactive `GET /dashboard`**: replaced the old minimal server-rendered
  job table with a single static HTML/CSS/vanilla-JS page (no build step, no
  framework, no new backend dependency). The page itself needs no auth and
  touches no database — a login box lets the user enter their `X-API-Key`
  (kept only in browser `localStorage`, never sent anywhere but back to this
  API), which the page then uses to fetch `GET /v1/assurance/jobs`
  client-side and render pass/warn/fail/indeterminate stat cards plus a
  client-side filterable/searchable job table. Still read-only, still no
  charts/trend graphs/server-side sessions.
- **Domain-agnostic run-history trend detection + server-side history
  lookup + opt-in alerting**:
  - `reconciliation.engine.compare_migration_run_history()` generalized to
    `compare_run_history()` — it only ever read the generic
    `{"checks": [...]}` report shape, so it now works unchanged against the
    run history of *any* domain (Claims, Coverage, etc.), not just
    migration batches. `compare_migration_run_history` is kept as a
    backward-compatible alias.
  - `db.repository.list_jobs_by_correlation()` fetches a pipeline's prior
    persisted jobs by `correlation_id`, oldest-first, so the API can supply
    run history to `compare_run_history()` from its own database instead of
    requiring the caller to resubmit old bundles/reports.
  - `POST /v1/assurance/compare` accepts an opt-in `include_trend: bool`
    request field (requires `correlation_id` and the `db` extra); when set,
    the endpoint looks up this pipeline's history server-side and appends
    `RUN.SYNC_GAP` / `RUN.CONTRACT_COMPLIANCE` / `RUN.POPULATION_DISTRIBUTION`
    / `*.LATE_UPDATE_OVERWRITTEN` trend findings to the response.
  - New `konkord.alerting` module: `send_alert()` optionally POSTs a
    non-PHI signal (`overall`, per-status counts, `correlation_id`,
    `job_id` — never `checks`/field values) to a webhook after every
    compare call. Off by default; enabled via `KONKORD_ALERT_WEBHOOK_URL`;
    fires only for `FAIL`/`WARN` runs by default (`KONKORD_ALERT_ON` to
    override); delivery failures are logged and never fail the request.
    Documented as a configurable `helm/konkord` `api.env` entry.
- **Goal, CareTeam, Risk Adjustment (DetectedIssue), CDex (Task), and
  DiagnosticReport** domains (SC-159–170), five new clinical/administrative
  assurance domains beyond the 158-scenario registry, covering additional
  US Core and Da Vinci Implementation Guides:
  - **Goal** (US Core Goal profile; SC-159/160): FHIR-to-FHIR
    `adapters.fhir.parse_fhir_goal_bundle()`/`load_fhir_goal_bundle()` and
    `reconciliation.engine.compare_many_goals()` checking
    `Goal.lifecycleStatus` and `Goal.achievementStatus` preservation.
  - **CareTeam** (US Core CareTeam profile; SC-161/162): FHIR-to-FHIR
    `adapters.fhir.parse_fhir_careteam_bundle()`/`load_fhir_careteam_bundle()`
    and `reconciliation.engine.compare_many_careteams()` checking
    `CareTeam.status` and `CareTeam.participant.member` reference
    preservation.
  - **Risk Adjustment** (Da Vinci Risk Adjustment "Gaps in Care &
    Information" IG; SC-163/164): FHIR-to-FHIR
    `adapters.fhir.parse_fhir_detectedissue_bundle()`/
    `load_fhir_detectedissue_bundle()` and
    `reconciliation.engine.compare_many_detected_issues()` checking
    `DetectedIssue.status` and `DetectedIssue.evidence.detail` reference
    preservation.
  - **CDex** (Da Vinci Clinical Data Exchange IG; SC-165/166): FHIR-to-FHIR
    `adapters.fhir.parse_fhir_task_bundle()`/`load_fhir_task_bundle()` and
    `reconciliation.engine.compare_many_tasks()` checking `Task.status` and
    `Task.businessStatus` preservation.
  - **DiagnosticReport** (US Core Laboratory Result profile; SC-167–170):
    HL7v2 ORU^R01 OBR (report header) to FHIR `DiagnosticReport`
    reconciliation via `adapters.hl7v2.parse_hl7_diagnosticreports()`
    (OBR-4/7/25), `adapters.fhir.parse_fhir_diagnosticreport_bundle()`/
    `load_fhir_diagnosticreport_bundle()`, the `diagnosticreport_observation`
    rule pack (`DIAGNOSTICREPORT.CODE`, `.STATUS`, `.EFFECTIVE_DATE`), and
    `reconciliation.engine.compare_many_diagnosticreports()`
    (missing-report detection + per-field checks). This is distinct from
    the existing Laboratory domain, which diffs individual OBX result
    values against FHIR `Observation`; this reconciles the OBR *report
    header* itself, which was previously only used for OBX specimen-type
    grouping and never diffed.
  - New example fixtures under `examples/` for each domain (source/target
    good/mismatch bundles, plus `diagnosticreport.hl7` and a `-missing`
    bundle), and new `GoalEngineTests`, `CareTeamEngineTests`,
    `DetectedIssueEngineTests`, `TaskEngineTests`, and
    `DiagnosticReportEngineTests` in `tests/test_engine.py`.
  - Registry is now 173 scenarios, 158 IMPLEMENTED.
- **Immunization** domain (SC-151–158), a new clinical assurance domain
  beyond the original 150-scenario registry: CDC/HL7 Immunization
  Implementation Guide reconciliation of VXU^V04 RXA (administration)
  segments against US Core `Immunization` resources. New
  `adapters.hl7v2.parse_hl7_immunizations()` (RXA-3/5/6/7/15/16/17/20),
  `adapters.fhir.parse_fhir_immunization_bundle()` /
  `load_fhir_immunization_bundle()`, the `immunization_observation` rule
  pack (`IMMUNIZATION.VACCINE_CODE`, `.DATE`, `.LOT_NUMBER`,
  `.EXPIRATION_DATE`, `.DOSE_AMOUNT`, `.DOSE_UNIT`, `.MANUFACTURER`,
  `.STATUS`), and `reconciliation.engine.compare_many_immunizations()`
  (missing/duplicate detection + per-field checks). Registry is now
  158 scenarios, 143 IMPLEMENTED.
- **`docs/IMPLEMENTATION-GUIDES.md`**: a reference table of every HL7 FHIR
  Implementation Guide and CMS rule Konkord's rule packs/adapters are
  written against (Da Vinci PDex Drug Formulary, PAS, PDex, Plan-Net, ATR;
  CARIN BB; US Core; HL7 Terminology; HL7v2.5.1), each row citing the
  canonical, always-current hl7.org URL rather than a pinned local copy,
  with the last-checked version number and the Konkord module implementing
  it, so a spec update can be traced directly to the code that may need a
  follow-up change.
- **HL7v2 missing-field group** (SC-044, SC-045, SC-052, SC-053, SC-055,
  SC-068): real HL7v2.5 AL1/DG1/PR1/IN1 segments have no clinical-status,
  verification-status, procedure-status, or coverage-status fields, so
  each adapter now also recognizes an optional, site-defined Z-segment
  (`ZAL`, `ZDG`, `ZPR`, `ZIN`) immediately following the base segment to
  carry that status, per standard HL7v2 trading-partner-extension
  convention. New rules `ALLERGY.CLINICAL_STATUS`/`ALLERGY
  .VERIFICATION_STATUS`, `CONDITION.CLINICAL_STATUS`/`CONDITION
  .VERIFICATION_STATUS`, `PROCEDURE.STATUS`, and `COVERAGE.STATUS`
  compare the Z-segment value against the FHIR R4B resource's
  `clinicalStatus`/`verificationStatus`/`status`; when the Z-segment is
  absent the check honestly returns INDETERMINATE rather than guessing.
- **CarePlan** and **ServiceRequest** reconciliation (SC-058, SC-059),
  both FHIR-to-FHIR (no HL7v2 analog): new `adapters.fhir.parse_fhir_careplan_bundle()`
  / `load_fhir_careplan_bundle()` and `parse_fhir_servicerequest_bundle()`
  / `load_fhir_servicerequest_bundle()`, plus `reconciliation.engine
  .compare_many_careplans()` (`CAREPLAN[id].GOAL`, `CAREPLAN[id].STATUS`)
  and `compare_many_servicerequests()` (`SERVICEREQUEST[id].INTENT`,
  `SERVICEREQUEST[id].STATUS`). SC-030 ("Condition detached from
  encounter") is now marked IMPLEMENTED too, since it's the same
  underlying check as SC-060 (`CONDITION[code].ENCOUNTER.REFERENCE`).
- **Longitudinal/job-history** reconciliation (SC-116, SC-117, SC-119,
  SC-120, SC-138): new `compare_migration_run_history()` and
  `compare_export_run_history()` functions in
  `src/konkord/reconciliation/engine.py` compare the current run against
  prior runs (using the existing `assurance_jobs`/`assurance_findings`
  history) to detect incremental sync gaps (`RUN.SYNC_GAP`), late updates
  silently overwritten (`RULE[id].LATE_UPDATE_OVERWRITTEN`), contract
  compliance degrading over time (`RUN.CONTRACT_COMPLIANCE`), per-rule
  field-population distribution shifts (`RULE[id].POPULATION_DISTRIBUTION`),
  and stale Da Vinci ATR bulk-export snapshots (`RUN.EXPORT_STALENESS`).
- **Formulary** domain (SC-141–150), completing the full scenario
  registry (135/150 IMPLEMENTED; the remaining 15 scenarios
  documented as genuinely out of scope for a single source/target
  comparison engine -- see `docs/scenario-registry.csv` for the
  per-scenario rationale). Da Vinci PDex US Drug Formulary
  reconciliation, FHIR-to-FHIR (no HL7v2 analog). Since R4B has no
  native Formulary/FormularyItem resource type, both are modeled as
  `Basic` resources distinguished by `Basic.code.coding[0].code`
  ("Formulary"/"FormularyItem") per the IG, with formulary-specific data
  carried as `Basic.extension` entries. `src/konkord/adapters/fhir.py`
  adds R4B `Basic`/`MedicationKnowledge` model support,
  `parse_fhir_formulary_bundle()`/`load_fhir_formulary_bundle()`
  (collecting `items`, `formularies`, `medications`,
  `insurance_plans`), and a new `_ext_value()` helper for reading
  `extension[].value[x]` by URL regardless of value type.
  `compare_many_formulary()` in the reconciliation engine matches
  FormularyItems by `identifier` (or raw `Basic.id`) and reports:
  `ITEM[key].DRUG_TIER` (SC-141), `ITEM[key].COST_SHARE` (SC-142,
  normal + deductible), `ITEM[key].PRIOR_AUTH` (SC-143),
  `ITEM[key].STEP_THERAPY` (SC-144), `ITEM[key].MISSING` (SC-145, drug
  dropped from formulary), `ITEM[key].RXNORM` (SC-146, via
  `medicationReference` into `MedicationKnowledge.code`),
  `ITEM[key].QUANTITY_LIMIT` (SC-147), `ITEM[key].FORMULARY_LINK`
  (SC-148, `formularyReference` must resolve on both sides),
  `ITEM[key].PHARMACY_TYPE` (SC-149), and
  `FORMULARY[id].EFFECTIVE_DATE` (SC-150, via the matched Formulary's
  `effectivePeriod` extension). New fixtures
  (`examples/formulary-source-bundle.json`,
  `examples/formulary-target-bundle-good.json`,
  `examples/formulary-target-bundle-mismatch.json`) and
  `FormularyEngineTests` (3 tests). Registry now 114/150 IMPLEMENTED.
- **External reference-data group** (SC-093, SC-094, SC-095, SC-097,
  SC-098): implemented against small, explicitly bundled local reference
  tables shipped with Konkord (`_LOCAL_CODE_MAP`, `_APPROVED_VALUESET`,
  `_UCUM_CONVERSION`, `_DEPRECATED_CODES`, `_SNOMED_PARENT` in
  `src/konkord/rules/terminology_observation.py`) rather than a live
  external terminology server -- a deliberately narrow, deterministic
  scope where anything outside the bundled table returns INDETERMINATE.
  New rules: `TERMINOLOGY.LOCAL_MAPPING`, `TERMINOLOGY.VALUESET_BINDING`,
  `TERMINOLOGY.UCUM_CONVERSION`, `TERMINOLOGY.DEPRECATED_CODE`,
  `TERMINOLOGY.SNOMED_SPECIFICITY`.
- **Structural-mapping defect group** (SC-100, SC-118): concrete,
  detectable instances of the structural-mapping defect class.
  `TERMINOLOGY.ELEMENT_MEANING_MOVED` (SC-100) detects a source's
  alternate/secondary text (OBX-3.5) mapped into the primary coding's
  display element instead of the primary text (OBX-3.2).
  `RECORD[key].MAPPING_BEHAVIOR` (SC-118), added to
  `compare_migration_batch()`, detects a resource's `subject` reference
  relocated from the standard `Resource.subject` element into
  `extension[]` (or dropped/retargeted) during migration. Registry now
  116/150 IMPLEMENTED.
- **ATR (Member Attribution)** domain (SC-131–140): Da Vinci ATR
  reconciliation, FHIR-to-FHIR like Provider Directory and Prior
  Authorization/Claims (payer bulk-exported attribution list vs.
  provider-side panel from the ATR "Member Attribution List
  Reconciliation API"; no HL7v2 analog). `src/konkord/adapters/fhir.py`
  adds R4B `Group` model support and
  `parse_fhir_attribution_bundle()`/`load_fhir_attribution_bundle()`,
  which collect the bundle's `Group`(s), `Patient`s, `Coverage`s, and
  `Encounter`s. `compare_many_member_attribution()` in the reconciliation
  engine matches members by `Patient.identifier` (or raw `Patient.id`)
  across all target `Group`s and reports: `MEMBER[key].MISSING` (SC-131),
  `MEMBER[key].DUAL_ATTRIBUTION` (SC-132, member attributed under more
  than one distinct `managingEntity`), `MEMBER[key].ATTRIBUTION_PERIOD`
  (SC-133), `MEMBER[key].COVERAGE_REF` (SC-134),
  `CATEGORY[Group].MEMBER_COUNT` (SC-135),
  `GROUP[id].CONTRACT_ID` (SC-136, `Group.identifier`),
  `MEMBER[key].ENCOUNTER_HISTORY` (SC-137),
  `MEMBER[key].DECEASED` (SC-139, a deceased source `Patient` must be
  carried as `Group.member.inactive=true` in the target), and
  `GROUP[id].RISK_ADJUSTMENT` (SC-140, `Group.characteristic`
  [code=risk-adjustment]). SC-138 (stale bulk-export snapshot) remains
  PLANNED: detecting staleness needs longitudinal export history across
  multiple `$davinci-data-export` runs, which a single source/target
  snapshot pair cannot carry. New fixtures
  (`examples/attribution-source-bundle.json`,
  `examples/attribution-target-bundle-good.json`,
  `examples/attribution-target-bundle-mismatch.json`) and
  `MemberAttributionEngineTests` (3 tests). Registry now 104/150
  IMPLEMENTED.
- **Provider Directory** domain (SC-121–130): Da Vinci PDex Plan-Net
  reconciliation, FHIR-to-FHIR like Prior Authorization/Claims (no HL7v2
  analog for a provider directory). `src/konkord/adapters/fhir.py` adds
  R4B model support and `parse_fhir_provider_directory_bundle()`/
  `load_fhir_provider_directory_bundle()`, which group each
  `PractitionerRole` with its referenced `Practitioner`, `Location`(s),
  and `HealthcareService`(s), plus the bundle-level `Organization`s and
  `InsurancePlan`s. New `provider` rule pack
  (`src/konkord/rules/provider_observation.py`) covers `PROVIDER.NPI`
  (SC-121), `PROVIDER.NETWORK_STATUS` (SC-122), `PROVIDER.NEW_PATIENTS`
  (SC-124), `PROVIDER.SPECIALTY` (SC-125), and `PROVIDER.TERMINATION`
  (SC-129). `compare_many_provider_directory()` in the reconciliation
  engine matches entries by `PractitionerRole.identifier` (or practitioner
  id + organization id), reports `PROVIDER[key].MISSING`/`.DUPLICATE`, and
  adds cross-entry/whole-batch checks: `PROVIDER[key].LOCATION_ADDRESS`
  (SC-123), `PROVIDER[key].TELEHEALTH` (SC-127), `PROVIDER[key].PHONE`
  (SC-130), `PRACTITIONER[id].ORG_DUPLICATE` (SC-126, a practitioner
  listed under an organization in the target not declared by the source),
  and `PLAN[id].NETWORK_REF` (SC-128, `InsurancePlan.network[].reference`
  must resolve to an `Organization` present in the target bundle). New
  fixtures: `examples/provider-source-bundle.json`,
  `examples/provider-target-bundle-{good,mismatch}.json`. All 10 Provider
  Directory scenarios are `IMPLEMENTED`. Registry: 95/150 `IMPLEMENTED`.
- **Migration & Drift** domain (SC-111–120): a new comparison model,
  distinct from the single source/target record reconciliation used by
  every other domain. `src/konkord/adapters/fhir.py` adds
  `parse_fhir_resource_batch()`/`load_fhir_resource_batch()`, which flatten
  a FHIR Bundle into its resources regardless of resourceType (a batch
  extract, not a single resource type). `compare_migration_batch()` in the
  reconciliation engine matches each source-batch resource to a
  target-batch resource by `resourceType` + `id` (or, absent an id,
  `resourceType` + first `identifier.value`), and reports: `RECORD[key]
  .MISSING` (SC-111, source resource absent from target),
  `RECORD[key].DUPLICATE` (SC-112, more than one target resource matches
  the same key), `RECORD[key].LINEAGE` (SC-114, matched target resource
  must carry `Resource.meta.source` identifying its originating system),
  and `CATEGORY[resourceType].COUNT` (SC-113, aggregate per-resourceType
  count comparison across the whole batch, not tied to any single
  matched pair). New fixtures: `examples/migration-source-batch.json`,
  `examples/migration-target-batch-{good,mismatch}.json`. SC-115
  (provenance changed), SC-116 (incremental sync gap), SC-117 (late
  update overwritten), SC-118 (mapping behavior changed), SC-119
  (contract compliance degraded), and SC-120 (field population
  distribution changed) remain `PLANNED`: each needs either full FHIR
  `Provenance` modeling, longitudinal/multi-run sync metadata, or a
  statistical baseline across many migration runs -- none of which a
  single source/target batch snapshot carries. Registry: 85/150
  `IMPLEMENTED`.
- **Documents** domain (SC-101–110): new `document` rule domain covering
  HL7v2 TXA (Transcription Document Header) segments vs FHIR
  `DocumentReference` resources. `src/konkord/adapters/hl7v2.py` adds
  `parse_hl7_documents()`/`_parse_txa_fields()`; `src/konkord/adapters/
  fhir.py` adds `parse_fhir_document_bundle()`/`load_fhir_document_bundle()`
  and registers `DocumentReference` for structural validation.
  `src/konkord/rules/document_observation.py` adds `DOCUMENT.TYPE`
  (SC-103, TXA-2 vs `type.coding[].code`), `DOCUMENT.AUTHOR` (SC-104,
  TXA-9 vs `author[].reference`), `DOCUMENT.DATE` (SC-105, TXA-6 vs
  `date`, date-level comparison), `DOCUMENT.CONFIDENTIALITY` (SC-106,
  TXA-18 vs `securityLabel[].coding[].code`), `DOCUMENT.CONTENT_TYPE`
  (SC-110, TXA-3 vs `content[0].attachment.contentType`), and
  `DOCUMENT.SUPERSESSION` (SC-109, TXA-13 vs `relatesTo[code=replaces]`).
  `compare_many_documents()` added to the reconciliation engine with two
  engine-level checks: `DOCUMENT[id].ATTACHMENT` (SC-101, attachment
  url/data presence) and `DOCUMENT[id].PATIENT_REF` (SC-107, `subject
  .reference` vs the bundle's declared `Patient`). New fixtures:
  `examples/document.hl7`, `examples/document-bundle-{good,mismatch,
  missing}.json`. SC-102 (content hash changed) remains `PLANNED`: TXA is
  a metadata-only header without the document text, so it never carries a
  content hash to compare against. SC-108 (clinical note section missing)
  remains `PLANNED`: it requires structured document content (e.g. CDA
  sections), which TXA (header-only) does not carry. Registry: 81/150
  `IMPLEMENTED`.
- **Terminology** domain (SC-091–100): new `terminology` rule domain,
  kept deliberately separate from the existing `observation` domain so it
  cannot change the PASS/FAIL outcome of any existing lab-result
  reconciliation. `src/konkord/rules/terminology_observation.py` adds
  `TERMINOLOGY.SYSTEM` (SC-091, HL7v2 OBX-3.3 coding system mapped to its
  canonical URI vs FHIR `Observation.code.coding[].system`),
  `TERMINOLOGY.VERSION` (SC-092, OBX-3.7 coding-system version vs
  `coding[].version`), `TERMINOLOGY.DISPLAY` (SC-096, OBX-3.2 display text
  vs `coding[].display`), and `TERMINOLOGY.MULTI_CODING` (SC-099, OBX-3.4
  alternate coding vs a second `coding[]` entry). `compare_terminology()`
  added to the reconciliation engine. HL7v2 adapter's `_parse_obx_fields()`
  now parses the full CWE (Coded With Exceptions) structure of OBX-3
  (identifier/text/coding-system/alternate-identifier/alternate-text/
  alternate-coding-system/version) instead of just identifier+system. New
  fixtures: `examples/terminology.hl7`,
  `examples/terminology-observation-good.json`,
  `examples/terminology-observation-mismatch.json`. SC-093 (local code
  mapping), SC-094 (unapproved concept representation), SC-097 (deprecated
  code), and SC-098 (SNOMED specificity) remain `PLANNED`: each requires an
  external mapping/terminology-service/code-currency table Konkord does
  not have. SC-095 (UCUM conversion) remains `PLANNED`: requires real unit
  arithmetic beyond literal unit-code comparison. SC-100 (FHIR element
  meaning moved) remains `PLANNED`: it describes a structural-mapping
  defect class, not a single deterministic field comparison. Registry:
  73/150 `IMPLEMENTED`.
- Real HL7v2/FHIR libraries replace the prior hand-rolled parsers:
  `src/konkord/adapters/hl7v2.py` now tokenizes every message with the
  `hl7` library (grammar-correct segment/field/repetition/component
  splitting, proper escape-sequence handling) instead of naive
  `str.split("|")`/regex line-splitting, while preserving the existing
  field-extraction contract so all adapters/rules/tests are unaffected.
  `src/konkord/adapters/fhir.py` adds `validate_fhir_structure()`, which
  runs incoming FHIR resources (Bundle/Observation/Patient/Encounter/
  MedicationRequest/AllergyIntolerance) through `fhir.resources`' R4B
  pydantic models for real structural validation. This is intentionally
  non-blocking/advisory (reconciliation still proceeds against the raw
  dict): the `POST /v1/assurance/compare` endpoint now logs a structured
  `fhir_validation_warnings` warning when the target doesn't fully
  conform to R4B, without rejecting the request. New dependencies: `hl7`,
  `fhir.resources`. Fixed two genuine fixture bugs this validation caught:
  `examples/medication-bundle-*.json` `authoredOn` values lacked a
  timezone offset (invalid per the FHIR `dateTime` regex).
- Hardening: `X-API-Key` comparison now uses `hmac.compare_digest()`
  (constant-time) instead of `in`/`==`, closing a timing side-channel that
  could otherwise leak information about valid API keys byte-by-byte.
- Multi-patient batch reconciliation: `parse_hl7_oru_batch()` (HL7v2 adapter)
  splits a single ORU^R01 message containing multiple PID/PV1 groups into
  per-patient observation sets; `parse_fhir_bundle_multi()` (FHIR adapter)
  groups a Bundle containing multiple Patient resources the same way;
  `compare_batch()` (reconciliation engine) correlates source and target
  patient groups by MRN and runs the existing `compare_many()` logic per
  matched pair, reporting unmatched source/target patients as explicit
  `PATIENT[mrn].MATCH` findings (FAIL/WARN) instead of silently dropping
  them. This removes the prior single-patient-per-message limitation for
  real-world batch lab feeds. New fixtures: `examples/panel-batch.hl7`,
  `examples/panel-batch-bundle-good.json`.
- Three new Laboratory rules closing scenario-registry gaps: `LAB.PRECISION`
  (SC-006, decimal-place preservation; limited by JSON float parsing, which
  loses trailing zeros before the rule can see them), `LAB.VALUE_TYPE`
  (SC-007, detects a numeric OBX-2 `NM`/`SN` result unexpectedly rendered
  as `valueString` instead of `valueQuantity`), and `LAB.SPECIMEN` (SC-008,
  compares HL7 OBR-15 specimen type against FHIR
  `Observation.specimen.type.text`; literal comparison only). HL7v2 adapter
  now parses OBR segments and groups each OBX under its preceding OBR's
  specimen type (`parse_hl7_oru`), and OBX-2 is captured as `value_type`.
  Registry: SC-006/SC-007/SC-008 now `IMPLEMENTED` (33/150 total).
- Three new `PLANNED` scenario domains in `docs/scenario-registry.csv`
  (SC-121–SC-150, 10 scenarios each) targeting Da Vinci payer
  interoperability implementation guides: **Provider Directory** (PDex
  Plan-Net — NPI/network/specialty/address drift), **ATR / Member
  Attribution** (Da Vinci ATR — attribution-list-vs-panel reconciliation
  for Value-Based Care), and **Formulary** (PDex US Drug Formulary — tier,
  cost-share, prior-auth/step-therapy drift). No rule packs implemented
  yet; registry total is now 150 scenarios, 30 `IMPLEMENTED`. Noted in
  `docs/ROADMAP.md`.
- Functional API pod splitting: `src/konkord/api/app.py` now reads
  `KONKORD_API_ROLE` (`all` | `write` | `read` | `ops`) to selectively mount
  the compare endpoint, the read-only job endpoints, or the health/metrics
  endpoints. `helm/konkord/values.yaml` gained `api.pools`, a list of named
  deployment pools (e.g. `api-write`, `api-read`, `api-ops`), each rendering
  its own Deployment/Service/PodDisruptionBudget/HPA with independent
  replicas, resources, and ingress paths behind a single shared Ingress —
  letting write traffic scale/fail independently from reads and keeping
  `/healthz`/`/metrics` from being starved by request spikes. Defaults to a
  single `konkord-api` pool (`role=all`) for backwards compatibility.
  Documented with a worked multi-pool example in `README.md`.
- Clinical rule packs (`konkord.rules.condition_observation`,
  `konkord.rules.procedure_observation`): `CONDITION.CODE`,
  `CONDITION.ONSET_DATE`, `PROCEDURE.CODE`, `PROCEDURE.PERFORMER`,
  `PROCEDURE.DATE`, plus new `compare_many_conditions()` /
  `compare_many_procedures()` reconciliation paths comparing an HL7v2
  message's DG1 (diagnosis) and PR1[/ROL] (procedure) segments against FHIR
  Bundles of `Condition`/`Procedure` resources, with missing/duplicate
  detection, a diagnosis-to-encounter relationship check
  (`CONDITION[code].ENCOUNTER.REFERENCE`, comparing PV1-19 visit number
  against `Condition.encounter.reference`), and patient-reference
  consistency checks (mirrors `compare_many_allergies()`). Implements
  scenarios SC-051, SC-054, SC-056, SC-057, SC-060 from
  `docs/scenario-registry.csv`; SC-052/SC-053/SC-055 remain `PLANNED`
  because HL7v2.5 DG1/PR1 have no clinical-status, verification-status, or
  procedure-status fields to compare against, and SC-058/SC-059 remain
  `PLANNED` pending `CarePlan`/`ServiceRequest` adapters. New adapter
  functions: `adapters.hl7v2.parse_hl7_conditions()`,
  `adapters.hl7v2.parse_hl7_procedures()`,
  `adapters.fhir.parse_fhir_condition_bundle()` /
  `load_fhir_condition_bundle()`,
  `adapters.fhir.parse_fhir_procedure_bundle()` /
  `load_fhir_procedure_bundle()`. R4B structural validation extended to
  `Condition` and `Procedure`. New fixtures: `examples/clinical.hl7`,
  `examples/condition-bundle-{good,mismatch,missing}.json`,
  `examples/procedure.hl7`,
  `examples/procedure-bundle-{good,mismatch,missing}.json`.
- Coverage rule pack (`konkord.rules.coverage_observation`):
  `COVERAGE.EFFECTIVE_DATE`, `COVERAGE.EXPIRATION_DATE`,
  `COVERAGE.RELATIONSHIP`, `COVERAGE.MEMBER_ID`, `COVERAGE.PAYOR_REFERENCE`,
  `COVERAGE.GROUP_NUMBER`, `COVERAGE.PRIORITY`, plus a new
  `compare_many_coverages()` reconciliation path comparing an HL7v2
  message's IN1 (insurance) segments against a FHIR Bundle of `Coverage`
  resources, matched by member ID (IN1-49 vs `Coverage.subscriberId`).
  Engine-level checks (mirroring `PATIENT.REFERENCE`/`ENCOUNTER.DUPLICATE`)
  add `COVERAGE[member_id].BENEFICIARY` (Coverage.beneficiary.reference vs
  the bundle's declared Patient) and `COVERAGE[member_id].DUPLICATE`
  (>1 target Coverage sharing a member ID). Implements scenarios SC-061,
  SC-062, SC-063, SC-064, SC-065, SC-066, SC-067, SC-069, SC-070 from
  `docs/scenario-registry.csv`; SC-068 remains `PLANNED` because HL7v2.5
  IN1 has no coverage-status field to compare against FHIR
  `Coverage.status`. New adapter functions:
  `adapters.hl7v2.parse_hl7_coverage()`,
  `adapters.fhir.parse_fhir_coverage_bundle()` /
  `load_fhir_coverage_bundle()`. R4B structural validation extended to
  `Coverage`. New fixtures: `examples/coverage.hl7`,
  `examples/coverage-bundle-{good,mismatch,missing}.json`.
- Prior Authorization rule pack (`konkord.rules.priorauth_observation`):
  Konkord's first FHIR-to-FHIR domain. There is no HL7v2 analog for a
  prior-authorization request (the real-world wire format is X12 278,
  which Konkord does not parse), so "source" is itself modeled as a FHIR
  `Claim` (the request as submitted) and "target" as the corresponding
  FHIR `ClaimResponse` (the payer's decision), matched by identifier.
  New rules: `PRIORAUTH.STATUS`, `PRIORAUTH.AUTHORIZATION_ID`,
  `PRIORAUTH.APPROVED_QUANTITY`, `PRIORAUTH.VALIDITY_PERIOD`,
  `PRIORAUTH.DECISION_REASON`, `PRIORAUTH.WORKFLOW_SYNC`, plus a new
  `compare_many_prior_authorizations()` reconciliation path with
  missing/duplicate detection and two engine-level checks:
  `PRIORAUTH[id].SERVICE_MISMATCH` (every submitted `Claim.item` must
  have exactly one corresponding adjudicated `ClaimResponse.item`, via
  `itemSequence` correlation) and `PRIORAUTH[id].COVERAGE_LINK`
  (`Claim.insurance[].coverage.reference` must be preserved in
  `ClaimResponse.insurance[]`). Implements scenarios SC-071, SC-072,
  SC-074, SC-075, SC-077, SC-078, SC-079, SC-080 from
  `docs/scenario-registry.csv`; SC-073 and SC-076 remain `PLANNED`
  because base FHIR R4B `ClaimResponse.item` has no `productOrService`
  element and `ClaimResponse` has no `supportingInfo` echo of the
  request. New adapter functions: `adapters.fhir.parse_fhir_claim_bundle()`
  / `load_fhir_claim_bundle()`,
  `adapters.fhir.parse_fhir_claimresponse_bundle()` /
  `load_fhir_claimresponse_bundle()`. R4B structural validation extended
  to `Claim` and `ClaimResponse`. New fixtures:
  `examples/priorauth-claim-bundle.json`,
  `examples/priorauth-claimresponse-bundle-{good,mismatch,missing}.json`.
  Registry: 60/150 scenarios now `IMPLEMENTED`.
- Claims rule pack (`konkord.rules.claim_observation`): a second
  FHIR-to-FHIR domain alongside Prior Authorization. There is no HL7v2
  analog for a professional/institutional claim submission (the
  real-world wire format is X12 837/835, which Konkord does not parse),
  so "source" is modeled as a FHIR `Claim` (`use="claim"`, the request as
  submitted) and "target" as the corresponding FHIR
  `ExplanationOfBenefit` (the payer's adjudication), matched by
  identifier. New rules: `CLAIM.STATUS`, `CLAIM.BILLED_AMOUNT`,
  `CLAIM.CURRENCY`, `CLAIM.DIAGNOSIS_LINKAGE`, plus a new
  `compare_many_claims()` reconciliation path with missing/duplicate
  detection and two engine-level checks: `CLAIM[id].LINE_MISMATCH`
  (every submitted `Claim.item` must be preserved on the matching
  `ExplanationOfBenefit.item`, compared on sequence, `productOrService`,
  `servicedDate`, and `quantity`) and `CLAIM[id].EOB_LINK`
  (`ExplanationOfBenefit.claim.reference` must point back to the matched
  `Claim`'s id). Implements scenarios SC-081, SC-082, SC-083, SC-084,
  SC-085, SC-086, SC-087, SC-088, SC-090 from `docs/scenario-registry.csv`;
  SC-089 (payment adjustment omitted) remains `PLANNED` because
  `EOB.payment` is purely payer-adjudication data with no analog on the
  submitted `Claim` to reconcile against. New adapter functions:
  `adapters.fhir.parse_fhir_eob_bundle()` / `load_fhir_eob_bundle()`. R4B
  structural validation extended to `ExplanationOfBenefit`. New fixtures:
  `examples/claim-bundle.json`,
  `examples/eob-bundle-{good,mismatch,missing}.json`. Registry: 69/150
  scenarios now `IMPLEMENTED`.
- Allergy rule pack (`konkord.rules.allergy_observation`): `ALLERGY.CODE`,
  `ALLERGY.REACTION`, `ALLERGY.SEVERITY`, `ALLERGY.ONSET_DATE`, plus a new
  `compare_many_allergies()` reconciliation path comparing an HL7v2 message's
  AL1 (patient allergy) segments against a FHIR Bundle of
  `AllergyIntolerance` resources, with missing/duplicate detection and
  patient-reference consistency checks (mirrors `compare_many()` and
  `compare_many_medications()`). Implements scenarios SC-041, SC-042,
  SC-043, SC-046, SC-048, SC-050 from `docs/scenario-registry.csv`. New
  adapter functions: `adapters.hl7v2.parse_hl7_allergies()`,
  `adapters.fhir.parse_fhir_allergy_bundle()` /
  `load_fhir_allergy_bundle()`.
- Medication rule pack (`konkord.rules.medication_observation`): `MEDICATION.CODE`,
  `MEDICATION.DOSE_AMOUNT`, `MEDICATION.DOSE_UNIT`, `MEDICATION.ROUTE`,
  `MEDICATION.FREQUENCY`, `MEDICATION.STATUS`, `MEDICATION.DATE`, plus a new
  `compare_many_medications()` reconciliation path comparing an HL7v2 RDE^O11
  message (PID + ORC/RXE/RXR order groups) against a FHIR Bundle of
  `MedicationRequest` resources, with missing/duplicate order detection and
  patient-reference consistency checks (mirrors `compare_many()`). Implements
  scenarios SC-031 through SC-037 and SC-039 from `docs/scenario-registry.csv`.
  New adapter functions: `adapters.hl7v2.parse_hl7_rde()`,
  `adapters.fhir.parse_fhir_medication_bundle()` /
  `load_fhir_medication_bundle()`.
- Encounter rule pack (`konkord.rules.encounter_observation`): `ENCOUNTER.CLASS`,
  `ENCOUNTER.LOCATION`, `ENCOUNTER.ATTENDING`, `ENCOUNTER.PERIOD_START`, plus
  `ENCOUNTER.REFERENCE` in `compare_many()`, comparing the HL7v2 PV1 segment
  against the FHIR `Encounter` resource. Implements scenarios SC-021, SC-022,
  SC-023, SC-025, SC-026 from `docs/scenario-registry.csv`. The HL7v2 adapter
  now also extracts PV1 (patient class, location, attending provider, visit
  number, admit/discharge date-time), and the FHIR adapter extracts a Bundle's
  `Encounter` resource.
- Patient identity rule pack (`konkord.rules.identity_observation`): `IDENTITY.MRN`,
  `IDENTITY.ASSIGNING_AUTHORITY`, `IDENTITY.BIRTH_DATE`, `IDENTITY.DECEASED`, and
  `IDENTITY.NAME`, comparing the HL7v2 PID segment against the FHIR `Patient`
  resource. Implements scenarios SC-012, SC-013, SC-016, SC-017, SC-018 from
  `docs/scenario-registry.csv`. The HL7v2 PID parser now also extracts name,
  birth date, and deceased fields.
- Cross-record batch identity checks in `reconciliation.engine.compare_batch()`:
  `IDENTITY.COLLISION` (SC-019, two target Patients sharing one MRN) and
  `IDENTITY.MERGE` (SC-014, two source MRNs resolving to the same target
  Patient).
- `ENCOUNTER.DUPLICATE` (SC-029) in `compare_batch()`: a matched target
  Patient with more than one Encounter resource. `adapters.fhir.parse_fhir_bundle_multi()`
  now keeps all Encounters per patient (`all_encounters`) instead of
  silently dropping all but the first.
- `MEDICATION.REFILLS` (SC-038): compares HL7v2 RXE-12 (number of refills)
  against FHIR `MedicationRequest.dispenseRequest.numberOfRepeatsAllowed`.
  The HL7v2 RDE adapter now extracts RXE-12.
- `MED[code].REQUEST_CONFUSED_WITH_ADMINISTRATION` (SC-040) in
  `compare_many_medications()`: a source order's code matches a target
  `MedicationAdministration` instead of a `MedicationRequest`.
  `adapters.fhir.parse_fhir_medication_bundle()` now also captures
  `MedicationAdministration` resources from the bundle.
- Alembic migrations (`alembic/`) for the persistence layer, replacing
  reliance on `Base.metadata.create_all()` for production schema evolution.
  `init_db()` remains for local dev/tests. New optional dependency:
  `alembic` (part of the `db` extra).
- Optional `X-API-Key` authentication on all `/v1/*` routes, controlled by the
  `KONKORD_API_KEYS` environment variable (comma-separated list). Disabled by
  default for local development.
- Structured JSON request logging (stdlib `logging`, no new dependency),
  configurable via `KONKORD_LOG_LEVEL`.
- `GET /metrics` endpoint exposing request counts and latency in Prometheus
  text exposition format (no `prometheus_client` dependency required).
- `GET /healthz` now reports `auth_enabled`.
- GitHub Actions CI pipeline: unit tests across Python 3.10–3.12, Docker image
  build check, and Helm chart lint/render.
- `CONTRIBUTING.md` and `CODE_OF_CONDUCT.md` for open-source contributors.

## [0.2.0]

### Added

- Kubernetes deployment via a custom Helm chart (`helm/konkord/`): separate
  `konkord-api` (stateless, 2 replicas) and `konkord-postgres` (stateful, PVC)
  Deployments, Services, Secret, ConfigMap, and optional Ingress.
- Multi-stage `Dockerfile` and local `docker-compose.yml` for API + PostgreSQL.
- PostgreSQL/SQLite-backed persistence layer: `assurance_jobs` /
  `assurance_findings` tables, `POST /v1/assurance/compare` now persists a job,
  `GET /v1/assurance/jobs` and `GET /v1/assurance/jobs/{id}` to retrieve them.
- FastAPI REST API (`POST /v1/assurance/compare`, `GET /healthz`) wrapping the
  reconciliation engine, with Pydantic request/response schemas and OpenAPI docs.
- Expanded `scripts/derive_synthea_fixtures.py`'s `LOINC_PANEL`/`LAB_NAMES`
  from 6 codes (Glucose/Creatinine/Potassium/Sodium/Hemoglobin) to a full
  8-component Basic Metabolic Panel (adds BUN, Chloride, CO2, Calcium) plus
  CBC and lipid-panel analytes (Hematocrit, Platelets, WBC, Cholesterol
  total/HDL/LDL, Triglycerides) and alternate Blood-specimen LOINC code
  variants Synthea sometimes uses instead of Serum/Plasma codes; the derived
  `panel-synthea.hl7` / `panel-synthea-bundle-good.json` fixtures now carry
  the full 8-analyte BMP instead of just 2 results.
- Helm chart: `api-hpa.yaml` (`HorizontalPodAutoscaler`, opt-in via
  `api.autoscaling.enabled`) and `api-pdb.yaml` (`PodDisruptionBudget`,
  enabled by default) so the stateless `konkord-api` Deployment splits
  across more pods under load and stays available during node drains;
  optional `api.podAntiAffinity.enabled` spreads API pods across nodes.
- Extended `scripts/derive_synthea_fixtures.py` to also derive Medication
  (RDE^O11 / `MedicationRequest`) and Allergy (ADT^A04 / `AllergyIntolerance`)
  fixtures from real MITRE Synthea records, alongside the existing lab panel
  fixtures; fixed the panel derivation to carry the real patient's MRN,
  assigning authority, and name into the generated PID segment (previously a
  placeholder PID masked the Identity rule pack against real data) and to
  drop Synthea's `Observation.encounter` reference from the panel bundle
  since that fixture doesn't model an Encounter resource. Added
  `test_medication_good_no_failures` and `test_allergy_good_no_failures` to
  `SyntheaDerivedFixtureTests`.
- Synthetic test data generated from MITRE Synthea, with derived HL7 ORU
  messages and failure-mode fixtures (missing/duplicate/bad-patient-reference).

## [0.1.0]

### Added

- Initial modular package restructure: `adapters/` (HL7v2, FHIR), `rules/`
  (registry + rule packs), `reconciliation/` (compare/compare_many),
  `evidence/` (report building).
- Core single-observation HL7 OBX vs. FHIR Observation reconciliation engine.
- Project renamed from `healthassure` to **Konkord**.
- Apache-2.0 license.
