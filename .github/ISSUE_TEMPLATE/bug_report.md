---
name: Bug report
about: Report incorrect reconciliation output, a crash, or unexpected API behavior
title: "[Bug] "
labels: bug
---

**Describe the bug**
A clear description of what went wrong.

**To reproduce**
Steps to reproduce, ideally including:
- The HL7v2 message (redact any real patient data — use synthetic/Synthea-style data)
- The FHIR Bundle/Observation JSON
- The command or API request used

**Expected behavior**
What you expected `compare`/`compare_many` or the API to return.

**Actual behavior**
What actually happened (include the full `checks`/`overall` output or stack trace).

**Environment**
- Konkord version (`pip show konkord` or `pyproject.toml`):
- Python version:
- Deployment: CLI / local API / Docker Compose / Kubernetes (Helm)

**Additional context**
Anything else relevant (logs, `/metrics` output, etc).
