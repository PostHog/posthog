from typing import Any

import pytest

from posthog.hogql.parser import parse_select

from products.signals.backend.emission._github_alerts import repository_from_html_url
from products.signals.backend.emission.github_code_scanning_alerts import (
    GITHUB_CODE_SCANNING_ALERTS_CONFIG,
    github_code_scanning_alert_emitter,
)
from products.signals.backend.emission.github_dependabot_alerts import (
    GITHUB_DEPENDABOT_ALERTS_CONFIG,
    MAX_ADVISORY_DESCRIPTION_CHARS,
    github_dependabot_alert_emitter,
)
from products.signals.backend.emission.github_secret_scanning_alerts import (
    GITHUB_SECRET_SCANNING_ALERTS_CONFIG,
    github_secret_scanning_alert_emitter,
)
from products.signals.backend.emission.registry import SignalSourceTableConfig

DEPENDABOT = {
    "html_url": "https://github.com/acme/widgets/security/dependabot/7",
    "number": 7,
    "state": "open",
    "created_at": "2026-01-01T00:00:00Z",
    "ghsa_id": "GHSA-aaaa-bbbb-cccc",
    "cve_id": "CVE-2026-0001",
    "advisory_summary": "Prototype pollution in example-lib",
    "advisory_description": "example-lib merges untrusted keys into the object prototype.",
    "severity": "high",
    "package_ecosystem": "npm",
    "package_name": "example-lib",
    "vulnerable_version_range": "< 4.17.21",
    "first_patched_version": "4.17.21",
    "manifest_path": "frontend/package.json",
    "dependency_scope": "runtime",
}

CODE_SCANNING = {
    "html_url": "https://github.com/acme/widgets/security/code-scanning/12",
    "number": 12,
    "state": "open",
    "created_at": "2026-01-01T00:00:00Z",
    "rule_id": "py/sql-injection",
    "rule_description": "SQL query built from user-controlled sources",
    "rule_full_description": "Building a SQL query from user input lets an attacker change the query.",
    "rule_severity": "error",
    "security_severity_level": "high",
    "tool_name": "CodeQL",
    "message_text": "This query depends on a user-provided value.",
    "location_path": "app/views.py",
    "location_start_line": "42",
}

SECRET_SCANNING = {
    "html_url": "https://github.com/acme/widgets/security/secret-scanning/3",
    "number": 3,
    "state": "open",
    "created_at": "2026-01-01T00:00:00Z",
    "secret_type": "example_api_key",
    "secret_type_display_name": "Example API key",
    "validity": "active",
}

EMITTERS = [
    ("dependabot", github_dependabot_alert_emitter, DEPENDABOT),
    ("code_scanning", github_code_scanning_alert_emitter, CODE_SCANNING),
    ("secret_scanning", github_secret_scanning_alert_emitter, SECRET_SCANNING),
]

CONFIGS = [
    ("dependabot", GITHUB_DEPENDABOT_ALERTS_CONFIG),
    ("code_scanning", GITHUB_CODE_SCANNING_ALERTS_CONFIG),
    ("secret_scanning", GITHUB_SECRET_SCANNING_ALERTS_CONFIG),
]


def _selected_names(config: SignalSourceTableConfig) -> set[str]:
    return {field.rsplit(" AS ", 1)[-1] for field in config.fields}


def test_dependabot_full_record():
    output = github_dependabot_alert_emitter(1, DEPENDABOT)
    assert output is not None
    assert output.source_product == "github_dependabot"
    assert output.source_id == DEPENDABOT["html_url"]
    assert output.description == (
        "Prototype pollution in example-lib\n"
        "Repository: acme/widgets\n"
        "Package: example-lib (npm), vulnerable versions < 4.17.21, first patched version 4.17.21\n"
        "Manifest: frontend/package.json (runtime dependency)\n"
        "Severity: high\n"
        "Advisory: GHSA-aaaa-bbbb-cccc, CVE-2026-0001\n"
        "example-lib merges untrusted keys into the object prototype."
    )
    assert output.extra["number"] == "7"
    assert output.extra["repository"] == "acme/widgets"


def test_dependabot_without_patch_or_cve():
    output = github_dependabot_alert_emitter(
        1, {**DEPENDABOT, "first_patched_version": "", "cve_id": "", "dependency_scope": None}
    )
    assert output is not None
    assert "first patched version" not in output.description
    assert ", no patched version yet" in output.description
    assert "Manifest: frontend/package.json\n" in output.description
    assert "Advisory: GHSA-aaaa-bbbb-cccc\n" in output.description


def test_dependabot_long_advisory_is_truncated():
    output = github_dependabot_alert_emitter(1, {**DEPENDABOT, "advisory_description": "d" * 5000})
    assert output is not None
    assert "d" * MAX_ADVISORY_DESCRIPTION_CHARS in output.description
    assert "d" * (MAX_ADVISORY_DESCRIPTION_CHARS + 1) not in output.description


def test_code_scanning_full_record():
    output = github_code_scanning_alert_emitter(1, CODE_SCANNING)
    assert output is not None
    assert output.source_product == "github_code_scanning"
    assert output.source_id == CODE_SCANNING["html_url"]
    assert output.description == (
        "SQL query built from user-controlled sources\n"
        "Repository: acme/widgets\n"
        "This query depends on a user-provided value.\n"
        "Location: app/views.py:42\n"
        "Severity: high\n"
        "Tool: CodeQL\n"
        "Building a SQL query from user input lets an attacker change the query."
    )


@pytest.mark.parametrize(
    "overrides,expected_title,expected_location,expected_line",
    [
        ({"rule_description": ""}, "py/sql-injection", "Location: app/views.py:42", "42"),
        (
            {"location_start_line": "null"},
            "SQL query built from user-controlled sources",
            "Location: app/views.py",
            None,
        ),
        ({"location_start_line": ""}, "SQL query built from user-controlled sources", "Location: app/views.py", None),
    ],
)
def test_code_scanning_fallbacks(
    overrides: dict[str, Any], expected_title: str, expected_location: str, expected_line: str | None
):
    output = github_code_scanning_alert_emitter(1, {**CODE_SCANNING, **overrides})
    assert output is not None
    assert output.description.split("\n")[0] == expected_title
    assert f"{expected_location}\n" in output.description
    assert "null" not in output.description
    assert output.extra["location_start_line"] == expected_line


def test_code_scanning_repeated_text_appears_once():
    output = github_code_scanning_alert_emitter(
        1,
        {
            **CODE_SCANNING,
            "message_text": CODE_SCANNING["rule_description"],
            "rule_full_description": CODE_SCANNING["rule_description"],
        },
    )
    assert output is not None
    assert output.description.count(CODE_SCANNING["rule_description"]) == 1


@pytest.mark.parametrize(
    "overrides,expected_title",
    [
        ({}, "Exposed secret detected: Example API key"),
        ({"secret_type_display_name": None}, "Exposed secret detected: example_api_key"),
    ],
)
def test_secret_scanning_title(overrides: dict[str, Any], expected_title: str):
    output = github_secret_scanning_alert_emitter(1, {**SECRET_SCANNING, **overrides})
    assert output is not None
    assert output.source_product == "github_secret_scanning"
    assert output.description == f"{expected_title}\nRepository: acme/widgets\nSecret validity: active"


@pytest.mark.parametrize(
    "emitter,record,overrides",
    [
        (github_dependabot_alert_emitter, DEPENDABOT, {"advisory_summary": ""}),
        (github_dependabot_alert_emitter, DEPENDABOT, {"html_url": None}),
        (github_code_scanning_alert_emitter, CODE_SCANNING, {"rule_description": "", "rule_id": None}),
        (github_code_scanning_alert_emitter, CODE_SCANNING, {"html_url": "  "}),
        (github_secret_scanning_alert_emitter, SECRET_SCANNING, {"secret_type_display_name": "", "secret_type": ""}),
        (github_secret_scanning_alert_emitter, SECRET_SCANNING, {"html_url": ""}),
    ],
)
def test_record_without_id_or_text_is_skipped(emitter, record: dict[str, Any], overrides: dict[str, Any]):
    assert emitter(1, {**record, **overrides}) is None


@pytest.mark.parametrize("name,emitter,record", EMITTERS, ids=[name for name, _, _ in EMITTERS])
def test_missing_html_url_column_raises(name, emitter, record: dict[str, Any]):
    with pytest.raises(ValueError):
        emitter(1, {k: v for k, v in record.items() if k != "html_url"})


@pytest.mark.parametrize("name,emitter,record", EMITTERS, ids=[name for name, _, _ in EMITTERS])
def test_same_number_in_two_repositories_gives_two_source_ids(name, emitter, record: dict[str, Any]):
    other_repo = {**record, "html_url": record["html_url"].replace("acme/widgets", "acme/gadgets")}
    first, second = emitter(1, record), emitter(1, other_repo)
    assert first is not None and second is not None
    assert first.source_id != second.source_id
    assert second.extra["repository"] == "acme/gadgets"


@pytest.mark.parametrize(
    "html_url,expected",
    [
        ("https://github.com/acme/widgets/security/dependabot/7", "acme/widgets"),
        ("https://github.com/acme/my.repo-1/security/code-scanning/1", "acme/my.repo-1"),
        ("https://github.com/acme/widgets/issues/7", None),
        ("value-html_url", None),
        (None, None),
    ],
)
def test_repository_from_html_url(html_url: Any, expected: str | None):
    assert repository_from_html_url(html_url) == expected


@pytest.mark.parametrize("name,config", CONFIGS, ids=[name for name, _ in CONFIGS])
def test_query_parses_and_skips_closed_alerts(name, config: SignalSourceTableConfig):
    query = (
        f"SELECT {', '.join(config.fields)} FROM github_alerts "
        f"WHERE parseDateTimeBestEffort(toString({config.partition_field})) > now() - interval 1 day "
        f"AND {config.where_clause} LIMIT {config.max_records}"
    )
    parse_select(query)
    assert config.where_clause == "state = 'open'"


@pytest.mark.parametrize("name,config", CONFIGS, ids=[name for name, _ in CONFIGS])
def test_query_never_selects_secret_or_user_objects(name, config: SignalSourceTableConfig):
    columns = " ".join(config.fields)
    for forbidden in ("dismissed_by", "resolved_by", "push_protection_bypassed_by", "assignees"):
        assert forbidden not in columns
    assert "secret" not in _selected_names(config)
