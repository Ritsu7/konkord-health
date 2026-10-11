# Konkord — Healthcare Data Assurance Library

Vision: an extensible, open-source-first assurance library that verifies conformance, semantic preservation, data contracts, reconciliation and production interoperability drift across healthcare formats. Konkord is distributed as a pure Python package (`pip install konkord-health`) — import it directly in a script or notebook (e.g. a Databricks notebook), or run the bundled `konkord` CLI. There is no REST API, container image, or Kubernetes deployment.

**New here?** See [`docs/USER-GUIDE.md`](docs/USER-GUIDE.md) for a complete, step-by-step walkthrough of the CLI and library usage.

## Run the first working vertical slice (Python 3.10+; no third-party dependencies)

```bash
python -m unittest discover -s tests -v
PYTHONPATH=src python -m konkord compare --source examples/lab.hl7 --target examples/observation-good.json
PYTHONPATH=src python -m konkord compare --source examples/lab.hl7 --target examples/observation-bad.json --report report.json
PYTHONPATH=src python -m konkord compare --source examples/panel.hl7 --target examples/panel-bundle-good.json
```

On Windows PowerShell, replace `PYTHONPATH=src python` with `$env:PYTHONPATH='src'; python`.

The `observation-bad.json` example intentionally fails (exit code 1). The CLI parses an **ORU^R01-style HL7v2 message with one or more numeric OBX observations, one PID segment, and an optional PV1 segment**, and compares it against a **FHIR R4 Bundle (or single Observation)**. For each matched observation it checks concept code, value, unit, interpretation, reference range, result status, and timestamp; across the message it also detects **missing observations** (present in source, absent in target), **duplicate observations** (multiple target observations with the same code), and **inconsistent/missing patient and encounter references** between the Bundle's `Patient`/`Encounter` resources and each `Observation.subject`/`Observation.encounter`. It also runs a patient-identity rule pack (`IDENTITY.MRN`, `IDENTITY.ASSIGNING_AUTHORITY`, `IDENTITY.BIRTH_DATE`, `IDENTITY.DECEASED`, `IDENTITY.NAME`) comparing the HL7 PID segment against the Bundle's `Patient` resource, and an encounter rule pack (`ENCOUNTER.CLASS`, `ENCOUNTER.LOCATION`, `ENCOUNTER.ATTENDING`, `ENCOUNTER.PERIOD_START`) comparing the HL7 PV1 segment against the Bundle's `Encounter` resource. Matching is by LOINC code only — it does not perform complete FHIR conformance validation, terminology equivalence beyond exact LOINC code match, fuzzy record matching, or PHI de-identification. Use synthetic data only.

A separate medication path, `compare_many_medications()`, parses an **RDE^O11-style HL7v2 message with one PID segment and one or more ORC/RXE(/RXR) order groups** and compares it against a **FHIR R4 Bundle of `MedicationRequest` resources**. For each matched order (matched by RxNorm-style ingredient code) it runs the medication rule pack (`MEDICATION.CODE`, `MEDICATION.DOSE_AMOUNT`, `MEDICATION.DOSE_UNIT`, `MEDICATION.ROUTE`, `MEDICATION.FREQUENCY`, `MEDICATION.STATUS`, `MEDICATION.DATE`) and detects missing/duplicate orders and inconsistent patient references, the same pattern as `compare_many()`.

A third path, `compare_many_allergies()`, parses a message with one PID segment and one or more **AL1 (patient allergy) segments** and compares it against a **FHIR R4 Bundle of `AllergyIntolerance` resources**. For each matched allergy (matched by allergen code) it runs the allergy rule pack (`ALLERGY.CODE`, `ALLERGY.REACTION`, `ALLERGY.SEVERITY`, `ALLERGY.ONSET_DATE`) and detects missing/duplicate allergies and inconsistent patient references, the same pattern as the other `compare_many*()` functions.

**Scenario coverage:** `docs/scenario-registry.csv` tracks a 173-scenario backlog across Laboratory, Identity, Encounter, Medication, Allergy, Clinical, Coverage, Prior Authorization, Claims, Terminology, Documents, Migration/Drift, Provider Directory, Member Attribution, Formulary, CarePlan, ServiceRequest, Immunization, Goal, CareTeam, Risk Adjustment, CDex, and DiagnosticReport domains. As of this release, **166 of 173 scenarios are implemented** (see the `IMPLEMENTED` rows in the CSV); the remaining 7 are `PLANNED` and documented as out of scope for a single source/target snapshot comparison engine (e.g. ADT trigger-event message parsing not yet supported by the HL7v2 adapter, or FHIR/HL7v2 elements with no analog on the source side) — see `CHANGELOG.md` and `CONTRIBUTING.md`.

Additional synthetic scenarios: `examples/panel-bundle-missing.json` (missing observation), `examples/panel-bundle-duplicate.json` (duplicate observation), `examples/panel-bundle-bad-patient.json` (inconsistent patient reference). `examples/panel-synthea*`, `examples/medication-synthea*`, and `examples/allergy-synthea*` fixtures are derived from real [MITRE Synthea](https://github.com/synthetichealth/synthea) synthetic patient records (Lab/Identity/Encounter, Medication, and Allergy domains respectively) via `scripts/derive_synthea_fixtures.py`, exercised by `SyntheaDerivedFixtureTests` in `tests/test_engine.py`.

## Using Konkord as a library (e.g. in a Databricks notebook)

Install the package and call the engine functions directly — no server/process to run:

```bash
pip install "konkord-health[hl7]"
```

```python
from konkord.engine import parse_hl7_obx, load_observation, compare

source = parse_hl7_obx(open("lab.hl7").read())
target = load_observation("observation.json")
report = compare(source, target)
print(report["overall"])        # PASS | FAIL | WARN | INDETERMINATE
```

`compare_many()`, `compare_many_medications()`, `compare_many_allergies()`, and the other `compare_many_<domain>()` functions in `konkord.reconciliation.engine` follow the same pattern for bulk/domain-specific comparisons — pass parsed source + loaded FHIR bundle, get back a structured report dict.

## Optional: persisting comparison runs (PostgreSQL/SQLite)

Install the `db` extra (`sqlalchemy`, `psycopg[binary]`, `alembic`) to persist each comparison and inspect it later, either from the CLI (`--save`, `konkord jobs`, `konkord status`) or directly via `konkord.db.repository`:

```bash
pip install "konkord-health[db,hl7]"
export KONKORD_DATABASE_URL="postgresql+psycopg://konkord:konkord@localhost:5432/konkord"  # defaults to local sqlite:///./konkord.db
```

### Schema migrations (Alembic)

```bash
export KONKORD_DATABASE_URL="postgresql+psycopg://konkord:konkord@localhost:5432/konkord"
alembic upgrade head
```

Migration scripts live in `alembic/versions/`; `alembic/env.py` resolves the target database from the same `KONKORD_DATABASE_URL`. After changing `src/konkord/db/models.py`, generate a new revision with:

```bash
alembic revision --autogenerate -m "describe the change"
```

Always review autogenerated migrations before committing them.

## Contributing

This project is open source under Apache-2.0. See `CONTRIBUTING.md` for the dev setup and PR workflow, and `CODE_OF_CONDUCT.md` for community expectations. CI (`.github/workflows/ci.yml`) runs the test suite across Python 3.10–3.12 on every push and PR.

## Product design documents

- `docs/PRODUCT.md`: product boundaries, users, implemented capabilities, commercial positioning
- `docs/ARCHITECTURE.md`: modules, data-flow workflow, optional persistence
- `docs/SECURITY.md`: PHI/privacy threat model and prerequisites
- `docs/SCENARIOS.md`: how scenarios, rules, and fixtures differ, and the acceptance package each one requires
- `docs/IMPLEMENTATION-GUIDES.md`: the HL7/Da Vinci/US Core IG each rule pack and adapter is written against
- `docs/scenario-registry.csv`: 170 tracked scenarios across 20 domains (155 `IMPLEMENTED`, 15 `PLANNED`)

## Repository roadmap

- `src/konkord/`: modular engine (adapters, rules, reconciliation, evidence, optional db persistence); `engine.py` kept as a backward-compatible shim
- `tests/`: deterministic synthetic tests
- `examples/`: synthetic HL7 and FHIR fixtures
- `.github/workflows/`: baseline CI

## Principles

1. Reuse standards validators; do not claim that semantic assurance replaces conformance testing.
2. Explicit, versioned source-to-target mapping contracts are the basis of preservation checks.
3. Support `PASS`, `FAIL`, `WARN` and `INDETERMINATE`; don't guess equivalence.
4. Make every finding traceable and reproducible.
5. Run data-plane processing in customer-controlled environments by default.
6. Keep public demos and CI fixtures synthetic. Never send PHI to an LLM by default.

## Licensing / IP

Konkord is licensed under Apache-2.0 (see [`LICENSE`](LICENSE)). Confirm employer IP rights, contributor policy, terminology licenses and dependency licenses before publishing or accepting contributions. No HL7, LOINC, SNOMED CT or other third-party content is redistributed by this project.
