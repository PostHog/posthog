"""Signal emitter for veracode `sca_findings` (record kind: scanner_finding).

The table holds one row per vulnerable component and CVE per application, so one CVE in a shared library repeats once per application.
The fetcher groups rows by CVE and component file name, so each vulnerable component emits once.
The window is on the nested `finding_status.first_found_date`, and the ledger keys on the group alone.
The query reads only the CVE, component name and version from `finding_details`, not the component path.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._prompts import SCANNER_ACTIONABILITY_PROMPT, SCANNER_SUMMARIZATION_PROMPT
from products.signals.backend.emission._scanner import (
    SCANNER_GROUP_WINDOW_DAYS,
    datetime_expression,
    extra_from,
    hashed_source_id,
    plain_text,
    text_or_none,
)
from products.signals.backend.emission.fetchers.grouped_warehouse import grouped_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

MAX_DESCRIPTION_CHARS = 1500

_CVE_NAME = "JSONExtractString(toString(finding_details), 'cve', 'name')"
_COMPONENT = "JSONExtractString(toString(finding_details), 'component_filename')"
_FIRST_FOUND = "JSONExtractString(toString(finding_status), 'first_found_date')"

VERACODE_SCA_FIELDS = (
    "cve_name",
    "component_filename",
    "component_version",
    "finding_description",
    "max_severity",
    "affected_applications",
    "first_seen",
)

VERACODE_SCA_EXTRA_FIELDS = (
    "cve_name",
    "component_filename",
    "component_version",
    "max_severity",
    "affected_applications",
    "first_seen",
)

_SELECT_SQL = f"""
    {_CVE_NAME} AS cve_name,
    {_COMPONENT} AS component_filename,
    any(JSONExtractString(toString(finding_details), 'version')) AS component_version,
    any(description) AS finding_description,
    max(severity) AS max_severity,
    count(DISTINCT application_guid) AS affected_applications,
    min({_FIRST_FOUND}) AS first_seen
"""


def veracode_sca_source_id(record: dict[str, Any]) -> str:
    return hashed_source_id("veracode_sca", record.get("cve_name"), record.get("component_filename"))


def veracode_sca_finding_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        cve_name = text_or_none(record["cve_name"])
        component = text_or_none(record["component_filename"])
    except KeyError as e:
        msg = f"veracode_sca record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    if not cve_name and not component:
        logger.info(
            "Ignoring veracode_sca record with empty CVE and component",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None
    if cve_name and component:
        title = f"{cve_name} in {component}"
    else:
        title = cve_name or f"Vulnerable component {component}"
    parts = [title]
    details = plain_text(record.get("finding_description"), MAX_DESCRIPTION_CHARS)
    if details:
        parts.append(details)
    return SignalEmitterOutput(
        source_product="veracode_sca",
        source_type="scanner_finding",
        source_id=veracode_sca_source_id(record),
        description="\n".join(parts),
        weight=1.0,
        extra=extra_from(record, VERACODE_SCA_EXTRA_FIELDS),
    )


VERACODE_SCA_CONFIG = SignalSourceTableConfig(
    source_product="veracode_sca",
    source_type="scanner_finding",
    emitter=veracode_sca_finding_emitter,
    record_fetcher=grouped_warehouse_record_fetcher(
        select_sql=_SELECT_SQL,
        group_by_sql=f"{_CVE_NAME}, {_COMPONENT}",
        order_by_sql="max_severity DESC, first_seen DESC",
        source_id_for=veracode_sca_source_id,
        window_days=SCANNER_GROUP_WINDOW_DAYS,
    ),
    record_processed_outputs=True,
    partition_field=datetime_expression(_FIRST_FOUND),
    fields=VERACODE_SCA_FIELDS,
    where_clause=f"upper(JSONExtractString(toString(finding_status), 'status')) != 'CLOSED'",
    max_records=200,
    actionability_prompt=SCANNER_ACTIONABILITY_PROMPT,
    summarization_prompt=SCANNER_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
