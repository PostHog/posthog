from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions taken from the official openFDA field-reference docs (https://open.fda.gov/apis/).
# Keyed by endpoint name (matches ENDPOINTS / get_schemas). Partial coverage is fine — any endpoint,
# column, or table without an entry falls back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "drug_events": {
        "description": "Adverse event and medication error reports submitted to the FDA (FAERS). One row per safety report.",
        "docs_url": "https://open.fda.gov/apis/drug/event/",
        "columns": {
            "safetyreportid": "Unique identifier for the adverse event report.",
            "receivedate": "Date the FDA received the most recent version of this report (YYYYMMDD).",
            "receiptdate": "Date the FDA received this specific version of the report (YYYYMMDD).",
            "serious": "Whether the adverse event resulted in a serious outcome (1 = yes, 2 = no).",
            "patient": "Nested object describing the patient, their reactions, and the drugs involved.",
            "primarysource": "Nested object describing the qualification and country of the report's source.",
            "occurcountry": "Two-letter country code where the adverse event occurred.",
        },
    },
    "drug_labels": {
        "description": "Structured Product Labeling (SPL) — the FDA-approved prescription and OTC drug labeling content. One row per label document.",
        "docs_url": "https://open.fda.gov/apis/drug/label/",
        "columns": {
            "id": "Unique identifier for this label document version.",
            "set_id": "Identifier grouping all versions of a given product's label.",
            "effective_time": "Date the labeling became effective (format is inconsistent across records).",
            "openfda": "Nested object of harmonized identifiers (NDC, brand name, generic name, RxCUI, etc.).",
            "indications_and_usage": "The approved indications and usage section of the label.",
            "warnings": "The warnings section of the label.",
        },
    },
    "drug_ndc": {
        "description": "National Drug Code (NDC) Directory — every drug product currently or recently marketed in the U.S. One row per product.",
        "docs_url": "https://open.fda.gov/apis/drug/ndc/",
        "columns": {
            "product_id": "Unique identifier for the product (product NDC + SPL document id).",
            "product_ndc": "The labeler and product segments of the NDC.",
            "generic_name": "Generic name(s) of the drug.",
            "brand_name": "Brand or trade name of the drug.",
            "labeler_name": "Name of the company that labels or distributes the product.",
            "dosage_form": "The drug's dosage form (e.g. TABLET, INJECTION).",
            "product_type": "Product type (e.g. HUMAN PRESCRIPTION DRUG, HUMAN OTC DRUG).",
        },
    },
    "drug_enforcement": {
        "description": "Drug recall enforcement reports — recalls of drug products classified by the FDA. One row per recall.",
        "docs_url": "https://open.fda.gov/apis/drug/enforcement/",
        "columns": {
            "recall_number": "Unique FDA-assigned identifier for the recall.",
            "report_date": "Date the FDA published the enforcement report (YYYYMMDD).",
            "recall_initiation_date": "Date the recalling firm first notified the public or began the recall (YYYYMMDD).",
            "classification": "Recall class indicating relative health hazard (Class I, II, or III).",
            "status": "Current status of the recall (e.g. Ongoing, Completed, Terminated).",
            "recalling_firm": "Name of the firm that initiated the recall.",
            "reason_for_recall": "Explanation of why the product was recalled.",
            "product_description": "Description of the recalled product.",
        },
    },
    "device_events": {
        "description": "Medical device adverse event reports (MAUDE). One row per report of a device suspected of a death, injury, or malfunction.",
        "docs_url": "https://open.fda.gov/apis/device/event/",
        "columns": {
            "mdr_report_key": "Unique identifier for the Medical Device Report.",
            "date_received": "Date the FDA received the report (YYYYMMDD).",
            "event_type": "Type of adverse event (e.g. Death, Injury, Malfunction).",
            "device": "Nested object describing the device(s) involved.",
            "patient": "Nested object describing the patient outcome(s).",
            "report_number": "Report number assigned by the reporting entity.",
        },
    },
    "device_510k": {
        "description": "510(k) premarket notification clearances — devices cleared by the FDA as substantially equivalent to a legally marketed device. One row per clearance.",
        "docs_url": "https://open.fda.gov/apis/device/510k/",
        "columns": {
            "k_number": "Unique FDA-assigned 510(k) submission number.",
            "decision_date": "Date the FDA made its clearance decision (YYYY-MM-DD).",
            "decision_code": "Code for the FDA's decision (e.g. SESE = substantially equivalent).",
            "device_name": "Name of the cleared device.",
            "applicant": "Company that submitted the 510(k).",
            "product_code": "FDA product classification code for the device.",
        },
    },
    "device_enforcement": {
        "description": "Medical device recall enforcement reports. One row per recall.",
        "docs_url": "https://open.fda.gov/apis/device/enforcement/",
        "columns": {
            "recall_number": "Unique FDA-assigned identifier for the recall.",
            "report_date": "Date the FDA published the enforcement report (YYYYMMDD).",
            "classification": "Recall class indicating relative health hazard (Class I, II, or III).",
            "status": "Current status of the recall (e.g. Ongoing, Completed, Terminated).",
            "recalling_firm": "Name of the firm that initiated the recall.",
            "reason_for_recall": "Explanation of why the product was recalled.",
        },
    },
    "food_enforcement": {
        "description": "Food recall enforcement reports. One row per recall.",
        "docs_url": "https://open.fda.gov/apis/food/enforcement/",
        "columns": {
            "recall_number": "Unique FDA-assigned identifier for the recall.",
            "report_date": "Date the FDA published the enforcement report (YYYYMMDD).",
            "classification": "Recall class indicating relative health hazard (Class I, II, or III).",
            "status": "Current status of the recall (e.g. Ongoing, Completed, Terminated).",
            "recalling_firm": "Name of the firm that initiated the recall.",
            "reason_for_recall": "Explanation of why the product was recalled.",
        },
    },
    "food_events": {
        "description": "Food and cosmetic adverse event reports (CAERS). One row per report submitted to the FDA.",
        "docs_url": "https://open.fda.gov/apis/food/event/",
        "columns": {
            "report_number": "Unique identifier for the CAERS report.",
            "date_created": "Date the report was created in the CAERS database (YYYYMMDD).",
            "date_started": "Date the adverse event began (YYYYMMDD).",
            "products": "Nested list of products implicated in the report.",
            "reactions": "List of reactions reported by the consumer.",
            "outcomes": "List of outcomes (e.g. hospitalization, death) associated with the event.",
        },
    },
}
