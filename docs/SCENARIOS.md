# Scenario registry and test discipline

`scenario-registry.csv` tracks 170 checks across 20 domains; 155 are `IMPLEMENTED` (each with a rule, fixtures, and a regression test) and 15 are `PLANNED` (documented as out of scope for a single source/target snapshot comparison engine — see `CHANGELOG.md`). Each `IMPLEMENTED` row links to the rule/reconciliation function and fixture files that cover it.

## Definitions

- Scenario: concrete failure mode or quality question.
- Primitive: reusable logic (e.g. unit equivalence).
- Rule: parameterized, versioned assertion over mapped concepts.
- Contract: approved source/target expectations and exceptions.
- Fixture: source, target, contract, expected findings, terminology version.

## Required acceptance package per scenario

1. Positive fixture (preserved/allowed transformation).
2. Negative fixture (seeded defect).
3. Edge fixture (ambiguity or alternative representation).
4. Baseline result from existing validator/test tooling.
5. Evidence and remediation expectations.
6. Rule provenance, supported standard/profile versions and owner.
7. Explicit `INDETERMINATE` handling for unsupported equivalence.

## Coverage areas
Laboratory, identity, encounter, medication, allergies, diagnoses, coverage, prior authorization, claims, terminology, documents, migration/drift. Extend later to imaging, public health, SDOH, provider directory, API behavior, consent, privacy, de-identification, C-CDA, X12, NCPDP, OMOP and FHIR version upgrades.
