import json

import pytest
from unittest.mock import patch

from parameterized import parameterized
from posthoganalytics.request import APIError

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.config import DEFAULT_WIZARD_VERSION
from products.wizard.backend.facade.contracts import WizardProgram
from products.wizard.backend.facade.enums import WizardRunEnvironment
from products.wizard.backend.logic.programs import program_from_mapping, program_to_mapping
from products.wizard.backend.logic.registry.parser import parse_registry_payload

POSTHOG_INTEGRATION_PROGRAM = WizardProgram(
    id="posthog-integration",
    name="PostHog integration",
    description="Set up PostHog SDK integration",
    wizard_version=DEFAULT_WIZARD_VERSION,
    command=(),
    tags=(),
    required_programs=(),
    supported_environments=(WizardRunEnvironment.LOCAL, WizardRunEnvironment.CLOUD),
)

AUDIT_PROGRAM_PAYLOAD = {
    "id": "web-analytics-audit",
    "name": "Web analytics audit",
    "description": "Audit a project's web analytics setup",
    "wizard_version": "2.60.0",
    "command": ["audit", "web-analytics"],
    "tags": ["audit", "web-analytics"],
    "required_programs": ["posthog-integration"],
    "supported_environments": ["local"],
}

REGISTRY_PAYLOAD = {"version": 1, "programs": [AUDIT_PROGRAM_PAYLOAD]}


def test_registry_payload_parsing() -> None:
    registry = parse_registry_payload(REGISTRY_PAYLOAD)

    assert registry.programs[0].id == "web-analytics-audit"


@parameterized.expand(
    [
        ("unexpected_field", {**REGISTRY_PAYLOAD, "unexpected": "value"}),
        ("unsupported_version", {**REGISTRY_PAYLOAD, "version": 2}),
        ("duplicate_program", {"version": 1, "programs": [AUDIT_PROGRAM_PAYLOAD, AUDIT_PROGRAM_PAYLOAD]}),
    ]
)
def test_registry_rejects_invalid_serialized_value(_name: str, value: object) -> None:
    with pytest.raises(ValueError):
        parse_registry_payload(value)


def test_program_serialization_round_trip() -> None:
    program = program_from_mapping(AUDIT_PROGRAM_PAYLOAD)

    assert program_to_mapping(program) == AUDIT_PROGRAM_PAYLOAD
    assert program_from_mapping(program_to_mapping(program)) == program


@parameterized.expand(
    [
        ("unexpected_field", {**AUDIT_PROGRAM_PAYLOAD, "unexpected": "value"}),
        ("invalid_command", {**AUDIT_PROGRAM_PAYLOAD, "command": ["--override"]}),
        ("duplicate_environments", {**AUDIT_PROGRAM_PAYLOAD, "supported_environments": ["local", "local"]}),
    ]
)
def test_program_rejects_invalid_serialized_value(_name: str, value: object) -> None:
    with pytest.raises(ValueError):
        program_from_mapping(value)


def test_program_persisted_deserialization_accepts_legacy_wizard_version() -> None:
    persisted_value = {**AUDIT_PROGRAM_PAYLOAD, "wizard_version": "latest"}

    with pytest.raises(ValueError):
        program_from_mapping(persisted_value)

    assert program_from_mapping(persisted_value, allow_latest_version=True).wizard_version == "latest"


@parameterized.expand(
    [
        ("object", REGISTRY_PAYLOAD),
        ("json_string", json.dumps(REGISTRY_PAYLOAD)),
    ]
)
def test_registry_returns_personalized_programs(_name: str, payload: object) -> None:
    with patch("posthoganalytics.get_feature_flag_payload", return_value=payload) as get_payload:
        programs = wizard_facade.get_registry(distinct_id="user-distinct-id", organization_id="organization-id")

    assert programs == (
        WizardProgram(
            id="web-analytics-audit",
            name="Web analytics audit",
            description="Audit a project's web analytics setup",
            wizard_version="2.60.0",
            command=("audit", "web-analytics"),
            tags=("audit", "web-analytics"),
            required_programs=("posthog-integration",),
            supported_environments=(WizardRunEnvironment.LOCAL,),
        ),
    )
    get_payload.assert_called_once_with(
        "wizard-program-registry",
        distinct_id="user-distinct-id",
        groups={"organization": "organization-id"},
        group_properties={"organization": {"id": "organization-id"}},
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    )


def test_registry_preserves_valid_empty_program_list() -> None:
    with patch("posthoganalytics.get_feature_flag_payload", return_value={"version": 1, "programs": []}):
        programs = wizard_facade.get_registry(distinct_id="user-distinct-id", organization_id="organization-id")

    assert programs == ()


@parameterized.expand(
    [
        ("missing_payload", None),
        ("invalid_json", "{"),
        ("unsupported_version", {"version": 2, "programs": []}),
        ("duplicate_ids", {"version": 1, "programs": [AUDIT_PROGRAM_PAYLOAD, AUDIT_PROGRAM_PAYLOAD]}),
        (
            "missing_wizard_version",
            {
                "version": 1,
                "programs": [{key: value for key, value in AUDIT_PROGRAM_PAYLOAD.items() if key != "wizard_version"}],
            },
        ),
        (
            "mutable_wizard_version",
            {
                "version": 1,
                "programs": [{**AUDIT_PROGRAM_PAYLOAD, "wizard_version": "latest"}],
            },
        ),
        (
            "invalid_program",
            {
                "version": 1,
                "programs": [
                    AUDIT_PROGRAM_PAYLOAD,
                    {**AUDIT_PROGRAM_PAYLOAD, "id": "invalid-program", "command": ["--override"]},
                ],
            },
        ),
        (
            "unknown_environment",
            {
                "version": 1,
                "programs": [
                    {**AUDIT_PROGRAM_PAYLOAD, "supported_environments": ["hosted"]},
                ],
            },
        ),
    ]
)
def test_registry_falls_back_when_payload_is_invalid(_name: str, payload: object) -> None:
    with (
        patch("posthoganalytics.get_feature_flag_payload", return_value=payload),
        patch("products.wizard.backend.logic.registry.service.report_registry_fallback") as report_fallback,
    ):
        programs = wizard_facade.get_registry(distinct_id="user-distinct-id", organization_id="organization-id")

    assert programs == (POSTHOG_INTEGRATION_PROGRAM,)
    report_fallback.assert_called_once_with("invalid_payload")


def test_registry_does_not_hide_programming_errors() -> None:
    with (
        patch("posthoganalytics.get_feature_flag_payload", side_effect=RuntimeError("bug")),
        pytest.raises(RuntimeError, match="bug"),
    ):
        wizard_facade.get_registry(distinct_id="user-distinct-id", organization_id="organization-id")


def test_registry_falls_back_when_feature_flag_fetch_fails() -> None:
    with (
        patch("posthoganalytics.get_feature_flag_payload", side_effect=APIError(503, "Unavailable")),
        patch("products.wizard.backend.logic.registry.service.report_registry_fallback") as report_fallback,
    ):
        programs = wizard_facade.get_registry(distinct_id="user-distinct-id", organization_id="organization-id")

    assert programs == (POSTHOG_INTEGRATION_PROGRAM,)
    report_fallback.assert_called_once_with("request_failed")
