import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.ashby.source import AshbySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ashby import AshbySourceConfig


class TestAshbySource:
    def setup_method(self) -> None:
        self.source = AshbySource()
        self.team_id = 123
        self.config = AshbySourceConfig(api_key="ashby-key")

    @pytest.mark.parametrize(
        "status, schema_name, expected_valid, expected_message",
        [
            (200, None, True, None),
            (401, None, False, "Invalid Ashby API key"),
            # 403 at source-create is accepted (key may be scoped to a subset of endpoints).
            (403, None, True, None),
            # 403 for a specific schema is rejected.
            (403, "candidates", False, "Your Ashby API key does not have permission to read 'candidates'"),
            (400, None, False, "boom"),
        ],
    )
    def test_validate_credentials(
        self,
        status: int,
        schema_name: str | None,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        response = (
            ScriptedResponse(json={"success": False, "errors": ["boom"]})
            if status == 400
            else ScriptedResponse(status=status, json={"success": True})
        )
        with scripted_network([response]):
            is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)
        assert is_valid is expected_valid
        assert message == expected_message

    def test_validate_credentials_probes_schema_path_when_given(self) -> None:
        with scripted_network([ScriptedResponse(json={"success": True})]) as network:
            self.source.validate_credentials(self.config, self.team_id, schema_name="candidates")
        assert network.requests_log[0].path == "/candidate.list"
        assert network.requests_log[0].headers["authorization"] == "Basic YXNoYnkta2V5Og=="

    @pytest.mark.parametrize(
        "schema_name, expected_path, expected_body",
        [
            # The fan-out child methods need a parent id, so probing them directly always fails.
            ("application_history", "/application.list", {"limit": 1}),
            ("interview_stages", "/interviewPlan.list", {"limit": 1}),
            ("candidate_notes", "/candidate.list", {"limit": 1}),
            # These methods reject unknown request-body keys, so the probe must not send a limit.
            ("interview_stage_groups", "/interviewStageGroup.list", {}),
            ("application_hiring_team_roles", "/applicationHiringTeamRole.list", {}),
            # surveyType is required.
            ("survey_submissions", "/surveySubmission.list", {"limit": 1, "surveyType": "CandidateExperience"}),
        ],
    )
    def test_validate_credentials_sends_a_valid_probe_for_the_schema(
        self, schema_name: str, expected_path: str, expected_body: dict
    ) -> None:
        with scripted_network([ScriptedResponse(json={"success": True})]) as network:
            self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)
        assert network.requests_log[0].path == expected_path
        assert network.requests_log[0].json() == expected_body

    def test_validate_credentials_uses_default_probe_without_schema(self) -> None:
        with scripted_network([ScriptedResponse(json={"success": True})]) as network:
            self.source.validate_credentials(self.config, self.team_id)
        assert network.requests_log[0].path == "/department.list"

    def test_validate_credentials_rejects_unknown_schema_without_probing(self) -> None:
        with scripted_network([]) as network:
            is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name="not_a_table")
        assert is_valid is False
        assert message == "Unknown Ashby schema 'not_a_table'"
        assert network.requests_log == []
