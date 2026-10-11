# Contributing to Konkord

Thanks for your interest in improving Konkord! This document covers how to set up
your environment, our contribution workflow, and coding/testing expectations.

## Getting started

```bash
git clone <your-fork-url>
cd healthcare-assurance-starter
python3 -m pip install -e ".[api,db,dev]"
python3 -m unittest discover -s tests -v
```

All 26+ tests should pass before you start making changes.

## Development workflow

1. **Open an issue first** for anything beyond a trivial fix (typo, docs) so we can
   discuss the approach before you invest time.
2. **Branch from `main`.** Use a descriptive branch name, e.g. `feat/async-worker`
   or `fix/hl7-parsing-edge-case`.
3. **Write tests.** New rules, endpoints, or adapters should ship with unit tests in
   `tests/test_engine.py` (or a new `tests/test_*.py` file for a distinct area).
   We do not merge untested behavior changes.
4. **Keep the CLI/API/engine contract backward compatible** unless the PR explicitly
   says otherwise — this project validates real clinical interoperability data, so
   silent behavior changes are a correctness risk.
5. **Run the full test suite locally** before opening a PR:
   ```bash
   python3 -m unittest discover -s tests -v
   ```
6. **Open a pull request** against `main`, referencing the issue it closes. CI
   (`.github/workflows/ci.yml`) must pass: unit tests across Python 3.10–3.12,
   a Docker image build, and a Helm chart lint/render.

## Code structure

- `src/konkord/adapters/` — HL7v2 and FHIR parsing/loading.
- `src/konkord/rules/` — rule registry and domain-specific rule packs.
- `src/konkord/reconciliation/` — the comparison engine (`compare`, `compare_many`).
- `src/konkord/evidence/` — report/output building.
- `src/konkord/api/` — FastAPI REST layer (auth, logging, metrics, schemas).
- `src/konkord/db/` — SQLAlchemy persistence layer.
- `helm/konkord/` — Kubernetes Helm chart.

See `docs/ARCHITECTURE.md` for a deeper overview.

## Adding a new reconciliation rule

1. Add the rule function to the appropriate module in `src/konkord/rules/`.
2. Register it in `src/konkord/rules/registry.py`.
3. Add a fixture pair (good + at least one failing case) under `examples/`.
4. Add a test in `tests/test_engine.py` asserting the expected `status`/`rule_id`.

## Reporting security issues

Please do **not** open a public GitHub issue for security vulnerabilities. See
`docs/SECURITY.md` for the responsible-disclosure process.

## Code of Conduct

By participating in this project you agree to abide by our
[Code of Conduct](CODE_OF_CONDUCT.md).

## License

By contributing, you agree that your contributions will be licensed under the
project's [Apache-2.0 License](LICENSE).
