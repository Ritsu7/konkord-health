# HL7 / CMS implementation guides referenced by Konkord

Konkord does not vendor local copies of any HL7 FHIR Implementation Guide
(IG) or CMS rule text. Every domain's rule pack and adapter docstring cites
the **canonical, always-current HL7.org URL** for the profile/IG it checks
against, instead of a pinned local snapshot. This means:

- The mapping logic (code lists, field positions, status value sets) is
  reviewed against the live spec, not a frozen copy that can silently drift.
- When HL7 publishes a new IG version, only the version number below (and,
  if a breaking profile/element change applies, the affected rule pack)
  needs to be revisited -- there is no local spec text to keep in sync.
- Each table row's "Maps to" column is the Konkord module that implements
  that IG's checks, so a spec update can be traced directly to the code
  that may need a follow-up change.

**This table reflects versions verified at the time of writing (2026-10).
Always resolve the "Official URL" column at hl7.org for the current
published version** -- do not treat the version numbers below as pinned
dependencies; they are a last-checked bookmark, not a lockfile.

## Payer/member data exchange (Da Vinci, HL7 International)

| Domain | IG | Version (last checked) | Official URL | Maps to |
|---|---|---|---|---|
| Formulary | Da Vinci PDex US Drug Formulary | STU 2 (2.1.0) | `http://hl7.org/fhir/us/davinci-drug-formulary` | `reconciliation.engine.compare_many_formulary`, `adapters.fhir` (`Basic`-as-FormularyItem mapping) |
| Prior Authorization | Da Vinci Prior Authorization Support (PAS) | STU 2 (2.2.1) | `http://hl7.org/fhir/us/davinci-pas` | `rules.priorauth_observation` |
| Prior Authorization (solicitation) | Da Vinci Health Record Exchange (HRex) | STU 1 (1.2.0 current; 1.1.0 ballot referenced historically) | `http://hl7.org/fhir/us/davinci-hrex` | `rules.priorauth_observation` (ClaimResponse preauth profile) |
| Claims / EOB | Da Vinci Payer Data Exchange (PDex) | STU 2 (2.2.0) | `http://hl7.org/fhir/us/davinci-pdex` | `rules.claim_observation` |
| Claims (consumer-facing) | CARIN Consumer Directed Payer Data Exchange (CARIN IG for Blue Button) | STU 2 (2.2.0) | `http://hl7.org/fhir/us/carin-bb` | `rules.claim_observation` (ExplanationOfBenefit shape) |
| Provider Directory | Da Vinci PDex Plan-Net | STU 1 (1.2.0) | `http://hl7.org/fhir/us/davinci-pdex-plan-net` | `rules.provider_observation` |
| Member Attribution | Da Vinci Member Attribution (ATR) List | STU 2 (2.1.0) | `http://hl7.org/fhir/us/davinci-atr` | `reconciliation.engine.compare_many_member_attribution` |
| Risk Adjustment (DetectedIssue) | Da Vinci Risk Adjustment ("Gaps in Care & Information") | STU 1 (1.0.0) | `http://hl7.org/fhir/us/davinci-ra` | `reconciliation.engine.compare_many_detected_issues` |
| CDex (Task) | Da Vinci Clinical Data Exchange (CDex) | STU 2 (2.0.0) | `http://hl7.org/fhir/us/davinci-cdex` | `reconciliation.engine.compare_many_tasks` |

## Clinical data (US Core / base FHIR R4B)

| Domain | IG | Version (last checked) | Official URL | Maps to |
|---|---|---|---|---|
| Allergy, Condition, Procedure, Coverage, CarePlan, ServiceRequest, Goal, CareTeam, DiagnosticReport (Laboratory Result) | US Core | STU 7 (7.0.0) | `http://hl7.org/fhir/us/core` | `rules.allergy_observation`, `rules.condition_observation`, `rules.procedure_observation`, `rules.coverage_observation`, `rules.diagnosticreport_observation`, `reconciliation.engine.compare_many_careplans`/`compare_many_servicerequests`/`compare_many_goals`/`compare_many_careteams`/`compare_many_diagnosticreports` |
| Status/verification code systems (e.g. allergyintolerance-clinical, condition-clinical) | HL7 Terminology (THO) | 6.x/7.x (THO is continuously released; see each IG's dependency table) | `http://terminology.hl7.org` | Status-mapping tables in `rules.allergy_observation`, `rules.condition_observation`, `rules.coverage_observation` |

## HL7v2

| Domain | Standard | Maps to |
|---|---|---|
| ADT/ORU/RDE messages, AL1/DG1/PR1/IN1/TXA segments | HL7v2.5.1 (no single canonical web URL; see HL7 v2 Normative Edition via `https://www.hl7.org/implement/standards/product_brief.cfm?product_id=185`) | `adapters.hl7v2` |
| ZAL/ZDG/ZPR/ZIN site-defined Z-segments | Not a published HL7 standard -- these are Konkord's own trading-partner-extension convention, used because real HL7v2.5 AL1/DG1/PR1/IN1 have no clinical-status/verification-status/procedure-status/coverage-status field (see SC-044/SC-045/SC-052/SC-053/SC-055/SC-068 in `docs/scenario-registry.csv`) | `adapters.hl7v2._parse_zal_fields`/`_parse_zdg_fields`/`_parse_zpr_fields`/`_parse_zin_fields` |

## CMS rules this project's scope intersects with

| Rule | What it requires | Relevance here |
|---|---|---|
| CMS Interoperability and Prior Authorization Final Rule (CMS-0057-F) | Payer APIs (incl. Prior Auth, Provider Access, Payer-to-Payer) must use the Da Vinci PAS/PDex/Plan-Net/ATR IGs above | Konkord's Prior Auth, Formulary, Provider Directory, and Member Attribution domains check preservation of the exact fields these APIs are required to expose -- Konkord does not implement the APIs themselves, only post-hoc reconciliation of their payloads. |
| CMS Interoperability and Patient Access Final Rule (CMS-9115-F) | Patient Access API must expose claims/encounter/formulary data via CARIN BB / PDex Formulary | Same relationship as above for the Claims and Formulary domains. |

## Formulary data security (not a Konkord feature)

The Da Vinci PDex US Drug Formulary IG's "Security and Privacy
Considerations" section requires formulary data to be served over
SMART App Launch / OAuth 2.0 + TLS, with payer-side access control over
which client can query which member's plan-specific formulary. Konkord is
a batch/offline reconciliation engine, not a FHIR server or API gateway, so
it never serves formulary data to a client and has no transport/auth
surface of its own -- those controls belong to whatever system publishes
the formulary API being reconciled. See `docs/SECURITY.md` for Konkord's
own (data-at-rest/in-transit, PHI-minimization) requirements, and consult
the IG directly for the API-side security conformance clauses.
