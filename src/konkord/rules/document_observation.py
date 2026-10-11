"""Rule pack: clinical document metadata preservation checks (HL7v2 TXA
transcription-document-header segment -> FHIR DocumentReference).

Scope: covers scenario-registry.csv SC-103 (document category changed),
SC-104 (author lost), SC-105 (creation date changed), SC-106 (security
label omitted), SC-109 (supersession link lost), and SC-110 (MIME type
changed). SC-101 (attachment missing) and SC-107 (patient relationship
changed) are handled at the reconciliation-engine level, not here (they
need cross-record/bundle context, mirroring other domains' MISSING/
BENEFICIARY-style checks). SC-102 (content hash changed) is out of scope:
TXA is a metadata-only header without the document text, so it never
carries a content hash to compare against. SC-108 (clinical note section
missing) is out of scope: it requires structured document content (e.g.
CDA sections), which TXA (header-only) does not carry.

Like the other rule packs, checks are deterministic and never guess
clinical/business equivalence; insufficient evidence returns
INDETERMINATE.
"""
from __future__ import annotations
from .registry import register, RuleResult

DOMAIN = "document"


def _first_content(target: dict) -> dict:
    content = target.get("content", [])
    return content[0] if content else {}


@register("DOCUMENT.TYPE", domain=DOMAIN)
def check_type(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("code"):
        return RuleResult("INDETERMINATE", explanation="No source document type (TXA-2) supplied")
    if not target:
        return RuleResult("FAIL", source["code"], "", "Target has no DocumentReference resource")
    codes = [c.get("code", "") for c in target.get("type", {}).get("coding", [])]
    match = source["code"] in codes
    return RuleResult("PASS" if match else "FAIL", source["code"], codes,
                       "Document type preservation (TXA-2 vs DocumentReference.type.coding[].code)")


@register("DOCUMENT.AUTHOR", domain=DOMAIN)
def check_author(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("originator_id"):
        return RuleResult("INDETERMINATE", explanation="No source originator (TXA-9) supplied")
    if not target:
        return RuleResult("FAIL", source["originator_id"], "", "Target has no DocumentReference resource")
    authors = target.get("author", [])
    if not authors:
        return RuleResult("FAIL", source["originator_id"], [], "Target DocumentReference has no author")
    refs = [a.get("reference", "").split("/")[-1] for a in authors if a.get("reference")]
    match = source["originator_id"] in refs
    return RuleResult("PASS" if match else "FAIL", source["originator_id"], refs,
                       "Author preservation (TXA-9 Originator Code/Name vs DocumentReference.author[].reference)")


@register("DOCUMENT.DATE", domain=DOMAIN)
def check_date(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("origination_date"):
        return RuleResult("INDETERMINATE", explanation="No source origination date/time (TXA-6) supplied")
    raw = source["origination_date"]
    if len(raw) < 8:
        return RuleResult("INDETERMINATE", explanation="Source origination date not in supported YYYYMMDD... format")
    expected = f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
    if not target:
        return RuleResult("FAIL", expected, "", "Target has no DocumentReference resource")
    actual = (target.get("date") or "")[:10]
    return RuleResult("PASS" if expected == actual else "FAIL", expected, actual,
                       "Creation date preservation (TXA-6 vs DocumentReference.date, date-level comparison)")


@register("DOCUMENT.CONFIDENTIALITY", domain=DOMAIN)
def check_confidentiality(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("confidentiality_status"):
        return RuleResult("INDETERMINATE", explanation="No source confidentiality status (TXA-18) supplied")
    if not target:
        return RuleResult("FAIL", source["confidentiality_status"], "", "Target has no DocumentReference resource")
    labels = target.get("securityLabel", [])
    if not labels:
        return RuleResult("FAIL", source["confidentiality_status"], [],
                           "Target DocumentReference has no securityLabel")
    codes = [c.get("code", "") for label in labels for c in label.get("coding", [])]
    match = source["confidentiality_status"] in codes
    return RuleResult("PASS" if match else "FAIL", source["confidentiality_status"], codes,
                       "Security label preservation (TXA-18 vs DocumentReference.securityLabel[].coding[].code)")


@register("DOCUMENT.CONTENT_TYPE", domain=DOMAIN)
def check_content_type(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("content_presentation"):
        return RuleResult("INDETERMINATE", explanation="No source document content presentation (TXA-3) supplied")
    if not target:
        return RuleResult("FAIL", source["content_presentation"], "", "Target has no DocumentReference resource")
    actual = _first_content(target).get("attachment", {}).get("contentType", "")
    return RuleResult("PASS" if source["content_presentation"] == actual else "FAIL",
                       source["content_presentation"], actual,
                       "MIME type preservation (TXA-3 Document Content Presentation vs "
                       "DocumentReference.content[0].attachment.contentType)")


@register("DOCUMENT.SUPERSESSION", domain=DOMAIN)
def check_supersession(source: dict, target: dict) -> RuleResult:
    if not source or not source.get("parent_document_id"):
        return RuleResult("INDETERMINATE", explanation="No source parent document number (TXA-13) supplied")
    if not target:
        return RuleResult("FAIL", source["parent_document_id"], "", "Target has no DocumentReference resource")
    relates_to = target.get("relatesTo", [])
    replaces = [r for r in relates_to if r.get("code") == "replaces"]
    if not replaces:
        return RuleResult("FAIL", source["parent_document_id"], [],
                           "Target DocumentReference has no relatesTo[code=replaces] entry")
    targets = [r.get("target", {}).get("reference", "").split("/")[-1] for r in replaces]
    match = source["parent_document_id"] in targets
    return RuleResult("PASS" if match else "FAIL", source["parent_document_id"], targets,
                       "Supersession link preservation (TXA-13 Parent Document Number vs "
                       "DocumentReference.relatesTo[code=replaces].target.reference)")
