from collections.abc import Callable

from parameterized import parameterized

from products.warehouse_sources.sources.devin_ai._config import DevinAISourceConfig
from products.warehouse_sources.sources.devin_ai.devin_ai import DevinAIResumeConfig
from products.warehouse_sources.sources.devin_ai.source import DevinAISource
from products.warehouse_sources.sources.sdk.testing import RecordedRequest, ScriptedResponse, always, scripted_network


def _config(api_key: str = "cog_test", org_id: str = "org-abc") -> DevinAISourceConfig:
    return DevinAISourceConfig(api_key=api_key, org_id=org_id)


def _answers_by_path(answers: dict[str, int | BaseException]) -> Callable[[RecordedRequest], ScriptedResponse]:
    # Every path not named gets a 403, the answer of a table the key has no permission for.
    def respond(request: RecordedRequest) -> ScriptedResponse:
        answer = next((a for suffix, a in answers.items() if request.path.endswith(suffix)), 403)
        if isinstance(answer, BaseException):
            raise answer
        return ScriptedResponse(status=answer)

    return respond


class TestSourceConfig:
    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — required so the public docs render the table list.
        assert DevinAISource.lists_tables_without_credentials is True

    def test_connection_host_fields_force_secret_reentry_on_org_change(self) -> None:
        # Changing org_id retargets the stored API key at a different Devin org, so it must count as a
        # host field — editing it forces the user to re-enter the key.
        assert DevinAISource().connection_host_fields == ["org_id"]


class TestGetSchemas:
    @parameterized.expand(
        [
            # Secret metadata is opt-in, and session_messages costs one request per session in the
            # org's whole history — neither should turn on for a user who just wanted sessions.
            ("secrets", False),
            ("session_messages", False),
            ("sessions", True),
            ("session_insights", True),
            ("consumption_daily", True),
        ]
    )
    def test_costly_and_sensitive_tables_are_opt_in(self, endpoint: str, expected_default: bool) -> None:
        schemas = {s.name: s for s in DevinAISource().get_schemas(_config(), team_id=1)}
        assert schemas[endpoint].should_sync_default is expected_default


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("unauthorized", 401, None, False),
            # The key reads no table in the org (wrong org ID or no permissions), so every table would
            # fail on its first sync.
            ("forbidden_everywhere_at_create_is_rejected", 403, None, False),
            ("forbidden_for_schema_is_rejected", 403, "sessions", False),
            ("org_not_found", 404, None, False),
            ("unexpected", 500, None, False),
        ]
    )
    def test_status_code_mapping(self, _name: str, status: int, schema_name: str | None, expected_ok: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            ok, _err = DevinAISource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert ok is expected_ok
        assert network.requests_log[0].path == "/v3/organizations/org-abc/sessions"

    @parameterized.expand(
        [
            # A key without ViewOrgSessions can still sync the tables it has a permission for.
            ("one_other_table_readable", {"/playbooks": 200}, True, None),
            (
                "readable_table_after_a_probe_outage",
                {"/sessions/insights": ConnectionError("boom"), "/automations": 200},
                True,
                None,
            ),
            ("probe_outage_and_no_readable_table", {"/sessions/insights": ConnectionError("boom")}, False, "Try again"),
            ("server_error_and_no_readable_table", {"/playbooks": 500}, False, "Try again"),
        ]
    )
    def test_forbidden_sessions_at_create_probes_other_tables(
        self,
        _name: str,
        answers: dict[str, int | BaseException],
        expected_ok: bool,
        expected_error: str | None,
    ) -> None:
        with scripted_network(_answers_by_path(answers)):
            ok, err = DevinAISource().validate_credentials(_config(), team_id=1)
        assert ok is expected_ok
        if expected_error is None:
            assert err is None
        else:
            assert err is not None and expected_error in err


def test_resume_config_default_is_none() -> None:
    assert DevinAIResumeConfig().after is None
