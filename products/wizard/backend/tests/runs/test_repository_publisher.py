import base64
from types import SimpleNamespace

from unittest.mock import MagicMock, patch

from products.wizard.backend.logic.workers.repository_publisher import create_signed_commit


def _execution_result(*, stdout: str = "", exit_code: int = 0) -> SimpleNamespace:
    return SimpleNamespace(stdout=stdout, exit_code=exit_code)


def _graphql_response(payload: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(status_code=200, json=lambda: payload)


@patch("products.wizard.backend.logic.workers.repository_publisher.GitHubIntegration")
@patch("products.wizard.backend.logic.workers.repository_publisher.Integration.objects.filter")
def test_create_signed_commit_strips_head_sha_and_supports_binary_files(
    filter_integrations: MagicMock,
    github_integration_class: MagicMock,
) -> None:
    filter_integrations.return_value.first.return_value = MagicMock()
    github = github_integration_class.return_value
    github.api_request.side_effect = [
        _graphql_response({"data": {"repository": {"id": "R_1", "ref": None}}}),
        _graphql_response({"data": {"createRef": {"ref": {"name": "refs/heads/posthog/wizard-123"}}}}),
        _graphql_response({"data": {"createCommitOnBranch": {"commit": {"oid": "newsha456"}}}}),
    ]

    staged_contents = base64.b64encode(b"\x00\x01\x02").decode()
    sandbox = MagicMock()
    sandbox.execute.side_effect = [
        _execution_result(),
        _execution_result(stdout="7a6e71985f4e0058f10517fc662813a39818f805\n"),
        _execution_result(stdout="A\0src/config.py\0"),
        _execution_result(stdout=staged_contents),
    ]

    result = create_signed_commit(
        sandbox,
        team_id=7,
        integration_id=13,
        repository="posthog/posthog",
        branch="posthog/wizard-123",
        message="Set up PostHog",
        source="wizard",
    )

    create_ref_input = github.api_request.call_args_list[1].kwargs["json_body"]["variables"]["input"]
    commit_input = github.api_request.call_args_list[2].kwargs["json_body"]["variables"]["input"]
    assert create_ref_input["oid"] == "7a6e71985f4e0058f10517fc662813a39818f805"
    assert commit_input["expectedHeadOid"] == "7a6e71985f4e0058f10517fc662813a39818f805"
    assert result.commit_shas == ("newsha456",)
