# Security and PHI controls

**Konkord is NOT approved for PHI. Synthetic data only.** Reconciliation findings contain source and target values; those values could be PHI in real deployments.

## Production requirements before any PHI

- Formal HIPAA applicability, BAA and security/legal review where relevant.
- Data plane inside customer boundary; explicit egress policy and no default payload export.
- Findings classification and PHI minimization; safe error and audit schemas.
- Customer-managed encryption keys optional; encryption at rest and in transit.
- Namespace-aware HMAC tokenization with customer-held keys when matching requires it.
- Fine-grained RBAC, SSO, tenant isolation, audit, retention/deletion and incident response.
- Threat modeling, dependency and container scans, SBOM, pentesting, vulnerability process.
- Secrets never in rules, logs, reports or test fixtures.
- No LLM access to raw payloads by default; customer-hosted AI option after review.
- Terminology content licenses, third-party component licenses, and employer IP review.

Tokenization does not guarantee de-identification. Metadata, findings, timestamps and rare events can remain identifying.
