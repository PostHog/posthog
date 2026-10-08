from products.warehouse_sources.backend.temporal.data_imports.sources.abnormal_security.settings import API_DOCS_URL
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "threats": {
        "description": "Email threat campaigns detected by Abnormal, with recipient counts and a limited sample of messages.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "threatId": "Identifier of the threat campaign, which can affect multiple recipients.",
            "recipientCount": "Number of distinct recipients who received messages from this campaign.",
            "messages": "Message details returned by the API. The API limits this sample to 10 messages.",
            "tenantId": "Identifier of the tenant associated with this campaign.",
            "tenantName": "Short name of the tenant associated with this campaign.",
        },
    },
    "cases": {
        "description": "Account takeover cases detected by Abnormal. This table requires an Account Takeover license.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "caseId": "Unique identifier of the case.",
            "description": "Description of the case.",
            "severity_level": "Severity assigned to the case.",
            "confidence": "Confidence assigned to the case.",
            "last_modified": "Time when the case was last modified.",
            "first_observed": "Time when suspicious activity was first observed.",
            "created": "Time when the case was created.",
        },
    },
    "vendor_cases": {
        "description": "Vendor cases with security insights and a timeline of related events.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "vendorCaseId": "Unique identifier of the vendor case.",
            "vendorDomain": "Domain of the vendor associated with the case.",
            "firstObservedTime": "Time when the first message associated with the case arrived.",
            "lastModifiedTime": "Time when the case details were last modified.",
            "insights": "Security insights associated with the vendor case.",
            "timeline": "Timeline of events associated with the vendor case.",
        },
    },
}
