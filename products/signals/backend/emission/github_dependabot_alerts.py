"""Signal emitter for GitHub `dependabot_alerts` (record kind: scanner_finding).

The text is in nested JSON: `security_advisory` (summary, description, GHSA and CVE ids),
`security_vulnerability` (package, severity, version ranges) and `dependency` (manifest).
`dismissed_by` is a user object and is not selected. Only open alerts emit: the documented
states are `open`, `fixed`, `dismissed` and `auto_dismissed`.
"""

from typing import Any

from products.signals.backend.emission._github_alerts import alert_text, build_github_alert_output
from products.signals.backend.emission._prompts import SCANNER_ACTIONABILITY_PROMPT, SCANNER_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

SOURCE_PRODUCT = "github_dependabot"
MAX_ADVISORY_DESCRIPTION_CHARS = 1500

DEPENDABOT_FIELDS = (
    "html_url",
    "number",
    "state",
    "created_at",
    "JSONExtractString(toString(security_advisory), 'ghsa_id') AS ghsa_id",
    "JSONExtractString(toString(security_advisory), 'cve_id') AS cve_id",
    "JSONExtractString(toString(security_advisory), 'summary') AS advisory_summary",
    "JSONExtractString(toString(security_advisory), 'description') AS advisory_description",
    "JSONExtractString(toString(security_vulnerability), 'severity') AS severity",
    "JSONExtractString(toString(security_vulnerability), 'package', 'ecosystem') AS package_ecosystem",
    "JSONExtractString(toString(security_vulnerability), 'package', 'name') AS package_name",
    "JSONExtractString(toString(security_vulnerability), 'vulnerable_version_range') AS vulnerable_version_range",
    "JSONExtractString(toString(security_vulnerability), 'first_patched_version', 'identifier') AS first_patched_version",
    "JSONExtractString(toString(dependency), 'manifest_path') AS manifest_path",
    "JSONExtractString(toString(dependency), 'scope') AS dependency_scope",
)

DEPENDABOT_EXTRA_FIELDS = (
    "number",
    "state",
    "severity",
    "ghsa_id",
    "cve_id",
    "package_ecosystem",
    "package_name",
    "vulnerable_version_range",
    "first_patched_version",
    "manifest_path",
    "dependency_scope",
    "html_url",
    "created_at",
)


def _package_line(record: dict[str, Any]) -> str | None:
    name = alert_text(record.get("package_name"))
    if not name:
        return None
    ecosystem = alert_text(record.get("package_ecosystem"))
    line = f"Package: {name} ({ecosystem})" if ecosystem else f"Package: {name}"
    vulnerable = alert_text(record.get("vulnerable_version_range"))
    if vulnerable:
        line += f", vulnerable versions {vulnerable}"
    patched = alert_text(record.get("first_patched_version"))
    line += f", first patched version {patched}" if patched else ", no patched version yet"
    return line


def _manifest_line(record: dict[str, Any]) -> str | None:
    path = alert_text(record.get("manifest_path"))
    if not path:
        return None
    scope = alert_text(record.get("dependency_scope"))
    return f"Manifest: {path} ({scope} dependency)" if scope else f"Manifest: {path}"


def github_dependabot_alert_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    severity = alert_text(record.get("severity"))
    identifiers = ", ".join(i for i in (alert_text(record.get("ghsa_id")), alert_text(record.get("cve_id"))) if i)
    return build_github_alert_output(
        team_id=team_id,
        record=record,
        source_product=SOURCE_PRODUCT,
        title=alert_text(record.get("advisory_summary")),
        details=(
            _package_line(record),
            _manifest_line(record),
            f"Severity: {severity}" if severity else None,
            f"Advisory: {identifiers}" if identifiers else None,
            alert_text(record.get("advisory_description"), MAX_ADVISORY_DESCRIPTION_CHARS),
        ),
        extra_fields=DEPENDABOT_EXTRA_FIELDS,
    )


GITHUB_DEPENDABOT_ALERTS_CONFIG = SignalSourceTableConfig(
    source_product=SOURCE_PRODUCT,
    source_type="scanner_finding",
    emitter=github_dependabot_alert_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=DEPENDABOT_FIELDS,
    where_clause="state = 'open'",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=SCANNER_ACTIONABILITY_PROMPT,
    summarization_prompt=SCANNER_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
