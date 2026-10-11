# Konkord User Guide

Practical, step-by-step instructions for running Konkord. For *what* Konkord
does and does not do, see `docs/PRODUCT.md`; for *how it's built*, see
`docs/ARCHITECTURE.md`; for PHI/privacy handling, see `docs/SECURITY.md`.

## 1. Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[hl7,dev]"          # CLI + tests only
pip install -e ".[db,hl7,dev]"       # + Postgres/SQLite job persistence
```

In a Databricks notebook (or any other environment), install the published
package instead:

```bash
%pip install konkord-health
# or: pip install "konkord-health[db]" for Postgres/SQLite job persistence
```

Run the test suite anytime with:

```bash
rm -f ./konkord.db && python3 -m unittest discover -s tests -v
```

## 2. Use as a library

```python
from konkord import engine

report = engine.compare(source_text, target_bundle)
print(report["overall"], report["checks"])
```

Every `compare*()`/`compare_many_*()` function in `konkord.engine` (or
`konkord.reconciliation.engine`) returns a plain Python dict — no server, no
network call. This is the recommended way to use Konkord in a Databricks
notebook or any other Python pipeline: parse your source/target data (HL7v2
text, FHIR JSON/dict, NDJSON), call the relevant `compare*()` function, and
work with the returned `report` dict directly (write it to a Delta table,
log it, branch on `report["overall"]`, etc.).

## 3. CLI

The CLI has three commands: `compare` (run a reconciliation), `jobs` (list
persisted runs), and `status` (inspect one persisted run's findings).

### 3.1 `compare`

```bash
PYTHONPATH=src python -m konkord compare \
  --source examples/panel.hl7 \
  --target examples/panel-bundle-good.json
```

Exit code `0` means every check was `PASS`; non-zero means at least one
`FAIL`. The report (JSON) is printed to stdout — pipe it anywhere (CI logs,
`jq`, a file). See `README.md` for the other `compare_many_*()` fixture
pairs (medication, allergy, condition, procedure, coverage, claims, etc.)
under `examples/`.

`--target` also accepts an NDJSON file (`.ndjson`/`.ndjsonl`, one FHIR
resource per line — e.g. a FHIR Bulk Data export) instead of a single JSON
Bundle:

```bash
PYTHONPATH=src python -m konkord compare \
  --source examples/panel.hl7 \
  --target examples/panel-bundle-good.ndjson
```

See the `konkord-site` static site for the full data-ingestion reference
covering every supported format and submission method.

**Flags:**

| Flag | Required | Description |
| --- | --- | --- |
| `--source` | yes | HL7v2 ORU^R01 message file |
| `--target` | yes | FHIR JSON/NDJSON Bundle file |
| `--report` | no | Also write the JSON report to this file path |
| `--save` | no | Persist this report as a job (requires the `db` extra) |
| `--correlation-id` | no | Tag the saved job (only used with `--save`) |
| `--postgres-connection-string` | no | Connection string to persist to (only used with `--save`); see below |

By default (no `--save`) nothing touches a database. With `--save` and no
`--postgres-connection-string`, it persists to a local SQLite file,
`./konkord.db`, in the current working directory — no server or setup
required:

```bash
PYTHONPATH=src python -m konkord compare \
  --source examples/panel.hl7 --target examples/panel-bundle-good.json \
  --save --correlation-id pipeline-123
```

To persist to your own PostgreSQL instance instead, pass a connection
string (overrides the `KONKORD_DATABASE_URL` environment variable for that
one run):

```bash
PYTHONPATH=src python -m konkord compare \
  --source examples/panel.hl7 --target examples/panel-bundle-good.json \
  --save --postgres-connection-string "postgresql+psycopg://user:pass@host:5432/dbname"
```

### 3.2 `jobs` — list persisted runs

```bash
PYTHONPATH=src python -m konkord jobs --limit 20
PYTHONPATH=src python -m konkord jobs --postgres-connection-string "postgresql+psycopg://user:pass@host:5432/dbname"
```

Requires the `db` extra. Reads from the same database `compare --save`
wrote to (local SQLite by default, or `KONKORD_DATABASE_URL` /
`--postgres-connection-string` if set).

### 3.3 `status` — inspect one job's findings

```bash
PYTHONPATH=src python -m konkord status --job-id <job_id>
```

Prints the job's `overall` status plus every `FAIL`/`WARN` finding
discovered in that run. Exit code mirrors the job's `overall` (`1` for
`FAIL`, `0` otherwise). Accepts `--postgres-connection-string` the same way
as `compare`/`jobs`.

### 3.4 Opt-in alerting webhook

```python
from konkord import engine, alerting

report = engine.compare(source_text, target_bundle)
alerting.send_alert(report, webhook_url="https://example.com/hooks/konkord")
```

Or configure via environment variables and call `send_alert(report)` with no
arguments:

```bash
export KONKORD_ALERT_WEBHOOK_URL="https://example.com/hooks/konkord"
export KONKORD_ALERT_ON="FAIL,WARN"   # optional, this is the default
```

Sends only `overall`, per-status counts, `correlation_id`, `job_id` — never
field values or `checks`. Delivery failures are logged and never raise.
This is opt-in and must be called explicitly; it is not wired into
`compare()` or the CLI automatically.

## 4. Where to go next

- `docs/PRODUCT.md` — what's in/out of scope, target users.
- `docs/ARCHITECTURE.md` — module layout and data flow.
- `docs/SECURITY.md` — PHI/privacy threat model before using real data.
- `docs/scenario-registry.csv` — every tracked domain/scenario and its status.
