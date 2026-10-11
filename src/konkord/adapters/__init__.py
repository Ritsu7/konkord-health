"""Format-specific parsers (HL7v2, FHIR, ...) that produce plain-dict
intermediate representations consumed by the reconciliation engine.

Each adapter is independently extensible: new formats (C-CDA, X12, DICOM,
OMOP) are added as new modules here without changing the rule engine or
the reconciliation layer.
"""
