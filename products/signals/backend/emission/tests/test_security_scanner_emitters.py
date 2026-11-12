import pytest
from unittest.mock import MagicMock, patch

from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor

from products.signals.backend.emission.checkmarx_scan_results import (
    CHECKMARX_CONFIG,
    checkmarx_scan_result_emitter,
    checkmarx_source_id,
)
from products.signals.backend.emission.gitguardian_secret_incidents import gitguardian_secret_incident_emitter
from products.signals.backend.emission.infisical_secret_scanning_findings import (
    infisical_secret_scanning_finding_emitter,
)
from products.signals.backend.emission.jfrog_xray_violations import jfrog_xray_source_id, jfrog_xray_violation_emitter
from products.signals.backend.emission.semgrep_sca_findings import semgrep_sca_finding_emitter, semgrep_sca_source_id
from products.signals.backend.emission.sentinelone_threats import sentinelone_threat_emitter
from products.signals.backend.emission.veracode_findings import veracode_finding_emitter
from products.signals.backend.emission.veracode_sca_findings import veracode_sca_finding_emitter, veracode_sca_source_id

CHECKMARX = {
    "result_type": "sast",
    "similarity_id": "-1234567",
    "query_name": "SQL_Injection",
    "finding_description": "The application builds a query from user input.",
    "finding_severity": "HIGH",
    "finding_state": "TO_VERIFY",
    "first_seen": "2026-01-01T00:00:00Z",
    "scans": 3,
}

VERACODE = {
    "application_guid": "app-1",
    "issue_id": 42,
    "scan_type": "STATIC",
    "description": "<span>This call builds a SQL query</span>  <span>from untrusted input.</span>",
    "finding_severity": "4",
    "violates_policy": True,
    "cwe_name": "Improper Neutralization of Special Elements used in an SQL Command",
    "cwe_id": "89",
    "finding_category": "SQL Injection",
    "finding_state": "OPEN",
    "resolution_status": "NONE",
    "first_found_date": "2026-01-01T00:00:00.000Z",
}

VERACODE_SCA = {
    "cve_name": "CVE-2021-44228",
    "component_filename": "log4j-core-2.14.1.jar",
    "component_version": "2.14.1",
    "finding_description": "Remote code execution through JNDI lookups.",
    "max_severity": 5,
    "affected_applications": 4,
    "first_seen": "2026-01-01T00:00:00.000Z",
}

SEMGREP_SCA = {
    "vulnerability_identifier": "CVE-2022-25883",
    "package_name": "semver",
    "fallback_rule": "",
    "ecosystem": "npm",
    "rule_title": "semver ReDoS",
    "rule_text": "Versions of semver before 7.5.2 are vulnerable to ReDoS.",
    "finding_severity": "medium",
    "reachability_state": "reachable",
    "affected_findings": 2,
    "first_seen": "2026-01-01T00:00:00Z",
}

GITGUARDIAN = {
    "id": 7,
    "detector_display_name": "AWS Keys",
    "detector_name": "aws_iam",
    "severity": "critical",
    "validity": "valid",
    "status": "TRIGGERED",
    "occurrences_count": 2,
    "gitguardian_url": "https://dashboard.gitguardian.com/workspace/1/incidents/7",
    "date": "2026-01-01T00:00:00Z",
}

INFISICAL = {
    "id": "f-1",
    "rule": "aws-access-token",
    "resource_name": "example/api",
    "resource_type": "repository",
    "data_source_type": "github",
    "severity": "high",
    "status": "unresolved",
    "created_at": "2026-01-01T00:00:00Z",
}

SENTINELONE = {
    "id": "1900000000000000001",
    "threat_name": "example-dropper.exe",
    "classification": "Trojan",
    "confidence_level": "malicious",
    "analyst_verdict": "undefined",
    "incident_status": "unresolved",
    "threat_mitigation_status": "not_mitigated",
    "detection_type": "static",
    "created_at": "2026-01-01T00:00:00Z",
}

JFROG_XRAY = {
    "issue_id": "XRAY-123",
    "violation_description": "A prototype pollution in lodash allows code execution.",
    "violation_severity": "High",
    "violation_type": "Security",
    "violations": 5,
    "first_seen": "2026-01-01T00:00:00Z",
}


@pytest.mark.parametrize(
    "emitter,record,expected",
    [
        (
            checkmarx_scan_result_emitter,
            CHECKMARX,
            "SQL_Injection\nThe application builds a query from user input.",
        ),
        (
            checkmarx_scan_result_emitter,
            {**CHECKMARX, "query_name": ""},
            "The application builds a query from user input.",
        ),
        (
            veracode_finding_emitter,
            VERACODE,
            "Improper Neutralization of Special Elements used in an SQL Command\n"
            "This call builds a SQL query from untrusted input.",
        ),
        (
            veracode_finding_emitter,
            {**VERACODE, "cwe_name": "", "description": None},
            "SQL Injection",
        ),
        (
            veracode_sca_finding_emitter,
            VERACODE_SCA,
            "CVE-2021-44228 in log4j-core-2.14.1.jar\nRemote code execution through JNDI lookups.",
        ),
        (
            veracode_sca_finding_emitter,
            {**VERACODE_SCA, "cve_name": "", "finding_description": None},
            "Vulnerable component log4j-core-2.14.1.jar",
        ),
        (
            semgrep_sca_finding_emitter,
            SEMGREP_SCA,
            "CVE-2022-25883 in semver\nsemver ReDoS\nVersions of semver before 7.5.2 are vulnerable to ReDoS.",
        ),
        (
            semgrep_sca_finding_emitter,
            {**SEMGREP_SCA, "vulnerability_identifier": None, "package_name": "", "rule_text": "null"},
            "semver ReDoS",
        ),
        (
            gitguardian_secret_incident_emitter,
            GITGUARDIAN,
            "Leaked secret detected in source code: AWS Keys\nSecret validity: valid\nOccurrences: 2",
        ),
        (
            gitguardian_secret_incident_emitter,
            {**GITGUARDIAN, "detector_display_name": "", "validity": None, "occurrences_count": None},
            "Leaked secret detected in source code: aws_iam",
        ),
        (
            infisical_secret_scanning_finding_emitter,
            INFISICAL,
            "Leaked secret detected in source code, matching the aws-access-token rule in repository example/api",
        ),
        (
            infisical_secret_scanning_finding_emitter,
            {**INFISICAL, "resource_name": None},
            "Leaked secret detected in source code, matching the aws-access-token rule",
        ),
        (
            sentinelone_threat_emitter,
            SENTINELONE,
            "Trojan threat detected: example-dropper.exe\nConfidence: malicious\nMitigation status: not_mitigated",
        ),
        (
            sentinelone_threat_emitter,
            {**SENTINELONE, "classification": "", "confidence_level": "", "threat_mitigation_status": ""},
            "Threat detected: example-dropper.exe",
        ),
        (
            jfrog_xray_violation_emitter,
            JFROG_XRAY,
            "Security violation XRAY-123\nA prototype pollution in lodash allows code execution.",
        ),
    ],
)
def test_description(emitter, record, expected):
    output = emitter(1, record)
    assert output is not None
    assert output.description == expected
    assert output.source_type == "scanner_finding"


@pytest.mark.parametrize(
    "emitter,record",
    [
        (checkmarx_scan_result_emitter, {**CHECKMARX, "similarity_id": ""}),
        (checkmarx_scan_result_emitter, {**CHECKMARX, "query_name": "", "finding_description": "<p> </p>"}),
        (veracode_finding_emitter, {**VERACODE, "application_guid": None}),
        (veracode_finding_emitter, {**VERACODE, "cwe_name": "", "finding_category": "null", "description": ""}),
        (veracode_sca_finding_emitter, {**VERACODE_SCA, "cve_name": "", "component_filename": ""}),
        (semgrep_sca_finding_emitter, {**SEMGREP_SCA, "vulnerability_identifier": "", "rule_title": None}),
        (gitguardian_secret_incident_emitter, {**GITGUARDIAN, "detector_display_name": "", "detector_name": "null"}),
        (infisical_secret_scanning_finding_emitter, {**INFISICAL, "rule": ""}),
        (sentinelone_threat_emitter, {**SENTINELONE, "threat_name": ""}),
        (jfrog_xray_violation_emitter, {**JFROG_XRAY, "violation_description": None}),
        (jfrog_xray_violation_emitter, {**JFROG_XRAY, "issue_id": ""}),
    ],
)
def test_record_without_id_or_text_is_skipped(emitter, record):
    assert emitter(1, record) is None


@pytest.mark.parametrize(
    "emitter,record,missing",
    [
        (checkmarx_scan_result_emitter, CHECKMARX, "similarity_id"),
        (veracode_finding_emitter, VERACODE, "issue_id"),
        (veracode_sca_finding_emitter, VERACODE_SCA, "component_filename"),
        (semgrep_sca_finding_emitter, SEMGREP_SCA, "vulnerability_identifier"),
        (gitguardian_secret_incident_emitter, GITGUARDIAN, "id"),
        (infisical_secret_scanning_finding_emitter, INFISICAL, "id"),
        (sentinelone_threat_emitter, SENTINELONE, "id"),
        (jfrog_xray_violation_emitter, JFROG_XRAY, "issue_id"),
    ],
)
def test_missing_required_column_raises(emitter, record, missing):
    with pytest.raises(ValueError):
        emitter(1, {key: value for key, value in record.items() if key != missing})


@pytest.mark.parametrize(
    "source_id_for,record,same_group_change,other_group_change",
    [
        (checkmarx_source_id, CHECKMARX, {"scans": 9, "finding_state": "CONFIRMED"}, {"result_type": "sca"}),
        (
            veracode_sca_source_id,
            VERACODE_SCA,
            {"affected_applications": 9, "max_severity": 3},
            {"component_filename": "log4j-core-2.15.0.jar"},
        ),
        (
            semgrep_sca_source_id,
            SEMGREP_SCA,
            {"affected_findings": 9, "first_seen": "2026-02-01T00:00:00Z"},
            {"package_name": "semver-fork"},
        ),
        (
            semgrep_sca_source_id,
            {**SEMGREP_SCA, "vulnerability_identifier": "", "fallback_rule": "semver-redos"},
            {"rule_title": "semver ReDoS", "affected_findings": 9},
            {"fallback_rule": "semver-prototype-pollution"},
        ),
        (jfrog_xray_source_id, JFROG_XRAY, {"violations": 9, "violation_severity": "Low"}, {"issue_id": "XRAY-124"}),
    ],
)
def test_grouped_source_id_keys_on_the_vulnerability_only(source_id_for, record, same_group_change, other_group_change):
    source_id = source_id_for(record)
    assert source_id_for({**record, **same_group_change}) == source_id
    assert source_id_for({**record, **other_group_change}) != source_id


def test_veracode_source_id_is_unique_per_application():
    first = veracode_finding_emitter(1, VERACODE)
    second = veracode_finding_emitter(1, {**VERACODE, "application_guid": "app-2"})
    assert first is not None and second is not None
    assert first.source_id == "app-1:42"
    assert second.source_id == "app-2:42"


def test_extra_values_are_strings_or_none():
    output = veracode_finding_emitter(1, {**VERACODE, "resolution_status": "", "cwe_id": "null"})
    assert output is not None
    assert output.extra["finding_severity"] == "4"
    assert output.extra["violates_policy"] == "True"
    assert output.extra["resolution_status"] is None
    assert output.extra["cwe_id"] is None


def test_checkmarx_group_filter_reads_the_latest_scan():
    captured: dict[str, ast.SelectQuery] = {}

    def fake_execute(query, **kwargs):
        captured["query"] = query
        return MagicMock(results=[], columns=[])

    with patch(
        "products.signals.backend.emission.fetchers.grouped_warehouse.execute_hogql_query", side_effect=fake_execute
    ):
        CHECKMARX_CONFIG.record_fetcher(MagicMock(), CHECKMARX_CONFIG, {"table_name": "checkmarx.scan_results"})
    having = captured["query"].having
    assert having is not None
    collector = _ArgMaxCollector()
    collector.visit(having)
    assert sorted(collector.pairs) == [("state", "scan_created_at"), ("status", "scan_created_at")]


class _ArgMaxCollector(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.pairs: list[tuple[str, ...]] = []

    def visit_call(self, node: ast.Call) -> None:
        if node.name == "argMax":
            self.pairs.append(tuple(str(arg.chain[0]) for arg in node.args if isinstance(arg, ast.Field)))
        super().visit_call(node)
