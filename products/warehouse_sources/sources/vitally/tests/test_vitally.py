from typing import Any, cast

import pytest
from unittest.mock import MagicMock, Mock, patch

from requests import HTTPError

from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network
from products.warehouse_sources.sources.vitally._config import VitallyRegionConfig, VitallySourceConfig
from products.warehouse_sources.sources.vitally.settings import CUSTOM_OBJECT_SCHEMA_PREFIX
from products.warehouse_sources.sources.vitally.source import VitallySource
from products.warehouse_sources.sources.vitally.vitally import (
    VitallyPaginator,
    VitallyResumeConfig,
    get_custom_object_records_resource,
    get_messages,
    list_custom_object_definitions,
    vitally_source,
)


def _no_resume() -> Mock:
    return Mock(can_resume=Mock(return_value=False))


def _make_response(json_data: dict[str, Any], status_code: int = 200) -> Mock:
    response = Mock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = json_data
    response.raise_for_status = Mock()
    return response


FEATURE_REQUEST_DEFINITION = {
    "id": "f5dcbbd6-c69d-4402-b00e-7a34a27aded5",
    "name": "featureRequest",
    "label": "Feature Request",
}
OPPORTUNITY_DEFINITION = {
    "id": "5b50ffc0-849e-47e4-9954-25071a7d3636",
    "name": "Opportunity",
    "label": "Opportunity",
}


class TestVitallyPaginator:
    @pytest.mark.parametrize(
        "body,start_value,expected_has_next,expected_cursor",
        [
            pytest.param({}, "1970-01-01", False, None, id="falsy_body_stops"),
            # Regression: an empty results page must not IndexError, it must cleanly end pagination.
            pytest.param({"results": [], "next": "cursor-2"}, "1970-01-01", False, None, id="empty_results_stops"),
            pytest.param(
                {"results": [{"updatedAt": "2026-01-02T00:00:00Z"}], "next": "cursor-2"},
                "1970-01-01",
                True,
                "cursor-2",
                id="newer_page_continues",
            ),
            pytest.param(
                {"results": [{"updatedAt": "1970-01-01T00:00:00Z"}], "next": "cursor-2"},
                "2026-01-01",
                False,
                None,
                id="older_than_start_stops",
            ),
        ],
    )
    def test_incremental_update_state(self, body, start_value, expected_has_next, expected_cursor) -> None:
        paginator = VitallyPaginator(incremental_start_value=start_value, should_use_incremental_field=True)

        paginator.update_state(_make_response(body))

        assert paginator._has_next_page is expected_has_next
        assert paginator._cursor == expected_cursor


class TestListCustomObjectDefinitions:
    @pytest.mark.parametrize(
        "pages,expected_defs,expected_call_count",
        [
            pytest.param(
                [{"results": [FEATURE_REQUEST_DEFINITION], "next": None}],
                [FEATURE_REQUEST_DEFINITION],
                1,
                id="single_page",
            ),
            pytest.param(
                [
                    {"results": [FEATURE_REQUEST_DEFINITION], "next": "cursor-2"},
                    {"results": [OPPORTUNITY_DEFINITION], "next": None},
                ],
                [FEATURE_REQUEST_DEFINITION, OPPORTUNITY_DEFINITION],
                2,
                id="paginates_until_next_is_null",
            ),
            pytest.param([{"results": [], "next": None}], [], 1, id="empty_results"),
        ],
    )
    def test_returns_definitions(self, pages, expected_defs, expected_call_count):
        with scripted_network([ScriptedResponse(json=page) for page in pages]) as network:
            defs = list_custom_object_definitions("secret", "EU", None)

        assert defs == expected_defs
        assert len(network.requests_log) == expected_call_count
        assert {request.path for request in network.requests_log} == {"/resources/customObjects"}
        assert [request.param("from") for request in network.requests_log[1:]] == [page["next"] for page in pages[:-1]]

    def test_raises_on_http_error(self):
        with scripted_network(always(ScriptedResponse(status=401, json={}))):
            with pytest.raises(HTTPError, match="401"):
                list_custom_object_definitions("secret", "EU", None)


class TestGetMessages:
    def test_raises_http_error_instead_of_keyerror_when_conversations_request_fails(self):
        # A non-2xx conversations list response carries an error body with no "results" key.
        # Previously get_messages indexed json["results"] directly, surfacing a misleading
        # KeyError('results'); now raise_for_status lets the real HTTP error through.
        with scripted_network(always(ScriptedResponse(status=401, json={"message": "Unauthorized"}))):
            with pytest.raises(HTTPError, match="401"):
                list(get_messages("secret", "EU", None, None, False, MagicMock(), _no_resume()))

    def test_handles_missing_results_key_without_keyerror(self):
        # Defensive: a 200 response that omits "results" must end pagination cleanly, not KeyError.
        with scripted_network([ScriptedResponse(json={"next": None})]):
            assert list(get_messages("secret", "EU", None, None, False, MagicMock(), _no_resume())) == []


class TestResume:
    @pytest.mark.parametrize(
        "endpoint, saved, script, expected_paths, expected_from, expected_ids",
        [
            pytest.param(
                "Organizations",
                VitallyResumeConfig(cursor="cursor-2"),
                [ScriptedResponse(json={"results": [{"id": "org-2"}], "next": None})],
                ["/resources/organizations"],
                ["cursor-2"],
                ["org-2"],
                id="list_endpoint_starts_at_saved_cursor",
            ),
            pytest.param(
                "Messages",
                VitallyResumeConfig(cursor="cursor-2", conversations_done=["c1"]),
                [
                    ScriptedResponse(json={"results": [{"id": "c1"}, {"id": "c2"}], "next": None}),
                    ScriptedResponse(json={"messages": [{"id": "m2"}]}),
                ],
                ["/resources/conversations", "/resources/conversations/c2"],
                ["cursor-2", None],
                ["m2"],
                id="messages_skip_conversations_already_handed_on",
            ),
            pytest.param(
                "Messages",
                VitallyResumeConfig(cursor=None, conversations_done=["c1"]),
                [
                    ScriptedResponse(json={"results": [{"id": "c3"}, {"id": "c1"}, {"id": "c2"}], "next": None}),
                    ScriptedResponse(json={"messages": [{"id": "m3"}]}),
                    ScriptedResponse(json={"messages": [{"id": "m2"}]}),
                ],
                ["/resources/conversations", "/resources/conversations/c3", "/resources/conversations/c2"],
                [None, None, None],
                ["m3", "m2"],
                id="messages_read_a_conversation_that_moved_ahead_of_finished_ones",
            ),
            pytest.param(
                "Organizations",
                VitallyResumeConfig(completed=True),
                [],
                [],
                [],
                [],
                id="list_endpoint_reads_nothing_after_its_last_page",
            ),
        ],
    )
    def test_resumes_from_saved_state(
        self,
        endpoint: str,
        saved: VitallyResumeConfig,
        script: list[ScriptedResponse],
        expected_paths: list[str],
        expected_from: list[str | None],
        expected_ids: list[str],
    ) -> None:
        driver = SourceDriver(
            VitallySource(),
            VitallySourceConfig(secret_token="secret", region=VitallyRegionConfig(subdomain="", selection="EU")),
        )

        result = driver.run(endpoint, script, resume_state=saved)

        assert result.raised is None
        assert result.paths == expected_paths
        assert result.params("from") == expected_from
        assert [row["id"] for row in result.rows] == expected_ids

    def test_messages_stage_each_conversation_before_its_messages(self) -> None:
        driver = SourceDriver(
            VitallySource(),
            VitallySourceConfig(secret_token="secret", region=VitallyRegionConfig(subdomain="", selection="EU")),
        )

        result = driver.run(
            "Messages",
            [
                ScriptedResponse(json={"results": [{"id": "c1"}, {"id": "c2"}], "next": "cursor-2"}),
                ScriptedResponse(json={"messages": [{"id": "m1"}]}),
                ScriptedResponse(json={"messages": []}),
                ScriptedResponse(json={"results": [], "next": None}),
            ],
        )

        assert result.raised is None
        assert result.items == [[{"id": "m1", "conversation_updated_at": None}]]
        assert result.saved_states == [
            VitallyResumeConfig(cursor=None, conversations_done=[]),
            VitallyResumeConfig(cursor=None, conversations_done=["c1"]),
            VitallyResumeConfig(cursor=None, conversations_done=["c1", "c2"]),
            VitallyResumeConfig(cursor="cursor-2"),
        ]


class TestFullRefreshEndpoints:
    @pytest.mark.parametrize(
        "endpoint, expected_path, expected_sort_by, expected_partition_keys",
        [
            pytest.param("Admins", "/resources/admins", None, None, id="admins"),
            pytest.param("Meetings", "/resources/meetings", "createdAt", None, id="meetings"),
            pytest.param(
                "Project_Templates", "/resources/projectTemplates", "createdAt", ["created_at"], id="project_templates"
            ),
            pytest.param(
                "Project_Categories",
                "/resources/projectCategories",
                "createdAt",
                ["created_at"],
                id="project_categories",
            ),
        ],
    )
    def test_walks_every_page(
        self,
        endpoint: str,
        expected_path: str,
        expected_sort_by: str | None,
        expected_partition_keys: list[str] | None,
    ) -> None:
        driver = SourceDriver(
            VitallySource(),
            VitallySourceConfig(secret_token="secret", region=VitallyRegionConfig(subdomain="", selection="EU")),
        )

        result = driver.run(
            endpoint,
            [
                ScriptedResponse(json={"results": [{"id": "row-1"}, {"id": "row-2"}], "next": "cursor-2"}),
                ScriptedResponse(json={"results": [{"id": "row-3"}], "next": None}),
            ],
        )

        assert result.raised is None
        assert result.paths == [expected_path, expected_path]
        assert result.params("from") == [None, "cursor-2"]
        assert result.params("sortBy") == [expected_sort_by, expected_sort_by]
        assert result.params("updatedAt") == [None, None]
        assert [row["id"] for row in result.rows] == ["row-1", "row-2", "row-3"]
        assert result.response is not None
        assert result.response.partition_keys == expected_partition_keys
        assert result.final_state == VitallyResumeConfig(completed=True)


class TestGetCustomObjectRecordsResource:
    @pytest.mark.parametrize("should_use_incremental_field", [False, True])
    def test_builds_resource(self, should_use_incremental_field):
        resource = get_custom_object_records_resource(
            "featureRequest", "f5dcbbd6", should_use_incremental_field=should_use_incremental_field
        )
        endpoint = cast(dict[str, Any], resource["endpoint"])

        assert endpoint["path"] == "/resources/customObjects/f5dcbbd6/instances"
        assert resource["name"] == f"{CUSTOM_OBJECT_SCHEMA_PREFIX}featureRequest"
        assert resource["table_name"] == "custom_object_featurerequest"

        params = cast(dict[str, Any], endpoint["params"])
        if should_use_incremental_field:
            assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
            assert params["sortBy"] == "updatedAt"
            updated_at_config = params["updatedAt"]
            assert isinstance(updated_at_config, dict)
            assert updated_at_config["type"] == "incremental"
            assert updated_at_config["cursor_path"] == "updatedAt"
        else:
            assert resource["write_disposition"] == "replace"
            assert params["updatedAt"] is None


class TestVitallySourceCustomObjectRouting:
    @patch("products.warehouse_sources.sources.vitally.vitally.rest_api_resource")
    @patch("products.warehouse_sources.sources.vitally.vitally.list_custom_object_definitions")
    def test_resolves_machine_name_to_custom_object_id(self, mock_list, mock_rest_api):
        mock_list.return_value = [FEATURE_REQUEST_DEFINITION, OPPORTUNITY_DEFINITION]
        mock_rest_api.return_value = iter([{"id": "rec-1"}, {"id": "rec-2"}])

        rows = list(
            vitally_source(
                secret_token="secret",
                region="EU",
                subdomain=None,
                endpoint=f"{CUSTOM_OBJECT_SCHEMA_PREFIX}featureRequest",
                team_id=1,
                job_id="job-1",
                logger=MagicMock(),
                db_incremental_field_last_value=None,
                resumable_source_manager=_no_resume(),
                should_use_incremental_field=False,
            )
        )

        assert rows == [{"id": "rec-1"}, {"id": "rec-2"}]
        rest_call_kwargs = mock_rest_api.call_args
        config = rest_call_kwargs.args[0]
        assert len(config["resources"]) == 1
        assert (
            config["resources"][0]["endpoint"]["path"]
            == "/resources/customObjects/f5dcbbd6-c69d-4402-b00e-7a34a27aded5/instances"
        )

    @patch("products.warehouse_sources.sources.vitally.vitally.list_custom_object_definitions")
    def test_raises_for_unknown_custom_object(self, mock_list):
        mock_list.return_value = [OPPORTUNITY_DEFINITION]

        with pytest.raises(ValueError, match="featureRequest"):
            list(
                vitally_source(
                    secret_token="secret",
                    region="EU",
                    subdomain=None,
                    endpoint=f"{CUSTOM_OBJECT_SCHEMA_PREFIX}featureRequest",
                    team_id=1,
                    job_id="job-1",
                    logger=MagicMock(),
                    db_incremental_field_last_value=None,
                    resumable_source_manager=_no_resume(),
                    should_use_incremental_field=False,
                )
            )


class TestVitallySourceGetSchemas:
    def _make_config(self):
        config = MagicMock()
        config.secret_token = "secret"
        config.region.selection = "EU"
        config.region.subdomain = None
        return config

    @patch("products.warehouse_sources.sources.vitally.source.list_custom_object_definitions")
    def test_skips_definitions_without_a_name(self, mock_list):
        mock_list.return_value = [{"id": "abc", "name": "", "label": "empty"}, FEATURE_REQUEST_DEFINITION]

        schemas = VitallySource().get_schemas(self._make_config(), team_id=1)

        dynamic = [s for s in schemas if s.name.startswith(CUSTOM_OBJECT_SCHEMA_PREFIX)]
        assert len(dynamic) == 1
        assert dynamic[0].name == f"{CUSTOM_OBJECT_SCHEMA_PREFIX}featureRequest"

    @patch("products.warehouse_sources.sources.vitally.source.list_custom_object_definitions")
    def test_names_filter_applies_to_both_static_and_dynamic(self, mock_list):
        mock_list.return_value = [FEATURE_REQUEST_DEFINITION]

        schemas = VitallySource().get_schemas(
            self._make_config(),
            team_id=1,
            names=["Accounts", f"{CUSTOM_OBJECT_SCHEMA_PREFIX}featureRequest"],
        )

        assert {s.name for s in schemas} == {"Accounts", f"{CUSTOM_OBJECT_SCHEMA_PREFIX}featureRequest"}

    @patch("products.warehouse_sources.sources.vitally.source.capture_exception")
    @patch("products.warehouse_sources.sources.vitally.source.list_custom_object_definitions")
    def test_static_schemas_survive_discovery_failure(self, mock_list, mock_capture):
        mock_list.side_effect = RuntimeError("Vitally API unavailable")

        schemas = VitallySource().get_schemas(self._make_config(), team_id=1)

        names = {s.name for s in schemas}
        assert {"Accounts", "Conversations", "Custom_Objects", "Messages"} <= names
        assert not any(s.name.startswith(CUSTOM_OBJECT_SCHEMA_PREFIX) for s in schemas)
        # Unexpected discovery failures are still captured for triage.
        mock_capture.assert_called_once()

    @patch("products.warehouse_sources.sources.vitally.source.capture_exception")
    @patch("products.warehouse_sources.sources.vitally.source.list_custom_object_definitions")
    def test_transient_egress_proxy_failure_is_not_captured(self, mock_list, mock_capture):
        # Regression: PostHog's own egress proxy briefly 502ing on the tunnel used to reach
        # Vitally was reported as an exception on every discovery run, even though it's not a
        # bug and the next attempt recovers on its own.
        mock_list.side_effect = ConnectionError(
            "HTTPSConnectionPool(host='example.rest.vitally.io', port=443): Max retries exceeded "
            "with url: /resources/customObjects?limit=100 (Caused by ProxyError('Cannot connect "
            "to proxy.', OSError('Tunnel connection failed: 502 Bad gateway')))"
        )

        schemas = VitallySource().get_schemas(self._make_config(), team_id=1)

        names = {s.name for s in schemas}
        assert {"Accounts", "Conversations", "Custom_Objects", "Messages"} <= names
        assert not any(s.name.startswith(CUSTOM_OBJECT_SCHEMA_PREFIX) for s in schemas)
        mock_capture.assert_not_called()


def test_config_reads_the_region_selection() -> None:
    config = VitallySourceConfig.from_dict(
        {"secret_token": "secret_token", "region": {"selection": "US", "subdomain": "subdomain"}}
    )

    assert config.secret_token == "secret_token"
    assert config.region is not None
    assert config.region.selection == "US"
    assert config.region.subdomain == "subdomain"
