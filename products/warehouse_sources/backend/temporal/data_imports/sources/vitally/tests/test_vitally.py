from typing import Any, cast

import pytest
from unittest.mock import MagicMock, Mock, patch

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.vitally.settings import (
    CUSTOM_OBJECT_SCHEMA_PREFIX,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.vitally.source import VitallySource
from products.warehouse_sources.backend.temporal.data_imports.sources.vitally.vitally import (
    VitallyPaginator,
    get_custom_object_records_resource,
    get_messages,
    list_custom_object_definitions,
    vitally_source,
)


def _make_response(json_data: dict[str, Any], status_code: int = 200) -> Mock:
    response = Mock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = json_data
    response.raise_for_status = Mock()
    return response


def _make_session(responses: list[Mock]) -> MagicMock:
    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    session.send.side_effect = responses
    # prepare_request returns its argument unchanged so the paginator's url updates
    # propagate to the next send() call.
    session.prepare_request.side_effect = lambda r: r
    return session


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
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.vitally.vitally.make_tracked_session")
    def test_returns_definitions(self, mock_session_factory, pages, expected_defs, expected_call_count):
        session = _make_session([_make_response(page) for page in pages])
        mock_session_factory.return_value = session

        defs = list_custom_object_definitions("secret", "EU", None)

        assert defs == expected_defs
        assert session.send.call_count == expected_call_count

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.vitally.vitally.make_tracked_session")
    def test_raises_on_http_error(self, mock_session_factory):
        bad = _make_response({}, status_code=401)
        bad.raise_for_status.side_effect = RuntimeError("401 Unauthorized")
        mock_session_factory.return_value = _make_session([bad])

        with pytest.raises(RuntimeError, match="401 Unauthorized"):
            list_custom_object_definitions("secret", "EU", None)


class TestGetMessages:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.vitally.vitally.make_tracked_session")
    def test_raises_http_error_instead_of_keyerror_when_conversations_request_fails(self, mock_session_factory):
        # A non-2xx conversations list response carries an error body with no "results" key.
        # Previously get_messages indexed json["results"] directly, surfacing a misleading
        # KeyError('results'); now raise_for_status lets the real HTTP error through.
        bad = _make_response({"message": "Unauthorized"}, status_code=401)
        bad.raise_for_status.side_effect = HTTPError("401 Client Error: Unauthorized", response=bad)
        mock_session_factory.return_value = _make_session([bad])

        with pytest.raises(HTTPError, match="401"):
            list(get_messages("secret", "EU", None, None, False, MagicMock()))

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.vitally.vitally.make_tracked_session")
    def test_handles_missing_results_key_without_keyerror(self, mock_session_factory):
        # Defensive: a 200 response that omits "results" must end pagination cleanly, not KeyError.
        mock_session_factory.return_value = _make_session([_make_response({"next": None})])

        assert list(get_messages("secret", "EU", None, None, False, MagicMock())) == []


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
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.vitally.vitally.rest_api_resource")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.vitally.vitally.list_custom_object_definitions"
    )
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

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.vitally.vitally.list_custom_object_definitions"
    )
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

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.vitally.source.list_custom_object_definitions"
    )
    def test_includes_static_endpoints_and_dynamic_custom_objects(self, mock_list):
        mock_list.return_value = [FEATURE_REQUEST_DEFINITION, OPPORTUNITY_DEFINITION]

        schemas = VitallySource().get_schemas(self._make_config(), team_id=1)

        names = {s.name for s in schemas}
        # Static endpoints
        assert {"Accounts", "Conversations", "Custom_Objects", "Messages"} <= names
        # Dynamic custom object schemas
        assert f"{CUSTOM_OBJECT_SCHEMA_PREFIX}featureRequest" in names
        assert f"{CUSTOM_OBJECT_SCHEMA_PREFIX}Opportunity" in names

        feature_request = next(s for s in schemas if s.name == f"{CUSTOM_OBJECT_SCHEMA_PREFIX}featureRequest")
        assert feature_request.label == "Feature Request"
        assert feature_request.supports_incremental is True
        assert feature_request.supports_append is True
        assert len(feature_request.incremental_fields) == 1

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.vitally.source.list_custom_object_definitions"
    )
    def test_skips_definitions_without_a_name(self, mock_list):
        mock_list.return_value = [{"id": "abc", "name": "", "label": "empty"}, FEATURE_REQUEST_DEFINITION]

        schemas = VitallySource().get_schemas(self._make_config(), team_id=1)

        dynamic = [s for s in schemas if s.name.startswith(CUSTOM_OBJECT_SCHEMA_PREFIX)]
        assert len(dynamic) == 1
        assert dynamic[0].name == f"{CUSTOM_OBJECT_SCHEMA_PREFIX}featureRequest"

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.vitally.source.list_custom_object_definitions"
    )
    def test_falls_back_to_machine_name_when_label_missing(self, mock_list):
        mock_list.return_value = [{"id": "abc", "name": "widget"}]

        schemas = VitallySource().get_schemas(self._make_config(), team_id=1)

        widget = next(s for s in schemas if s.name == f"{CUSTOM_OBJECT_SCHEMA_PREFIX}widget")
        assert widget.label == "widget"

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.vitally.source.list_custom_object_definitions"
    )
    def test_names_filter_applies_to_both_static_and_dynamic(self, mock_list):
        mock_list.return_value = [FEATURE_REQUEST_DEFINITION]

        schemas = VitallySource().get_schemas(
            self._make_config(),
            team_id=1,
            names=["Accounts", f"{CUSTOM_OBJECT_SCHEMA_PREFIX}featureRequest"],
        )

        assert {s.name for s in schemas} == {"Accounts", f"{CUSTOM_OBJECT_SCHEMA_PREFIX}featureRequest"}

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.vitally.source.list_custom_object_definitions"
    )
    def test_skips_discovery_when_only_static_schemas_requested(self, mock_list):
        schemas = VitallySource().get_schemas(self._make_config(), team_id=1, names=["Accounts", "Conversations"])

        mock_list.assert_not_called()
        assert {s.name for s in schemas} == {"Accounts", "Conversations"}

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.vitally.source.capture_exception")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.vitally.source.list_custom_object_definitions"
    )
    def test_credential_free_placeholder_config_skips_discovery(self, mock_list, mock_capture):
        # The public documentation catalog calls get_schemas with a placeholder config whose
        # `region` is an empty string, not a VitallyRegionConfig. Discovery must be skipped rather
        # than crash on `config.region.selection` and spam error tracking.
        source = VitallySource()

        schemas = source.get_schemas(source._placeholder_config(), team_id=0)

        mock_list.assert_not_called()
        mock_capture.assert_not_called()
        names = {s.name for s in schemas}
        assert {"Accounts", "Conversations", "Custom_Objects", "Messages"} <= names
        assert not any(s.name.startswith(CUSTOM_OBJECT_SCHEMA_PREFIX) for s in schemas)

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.vitally.source.capture_exception")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.vitally.source.list_custom_object_definitions"
    )
    def test_static_schemas_survive_discovery_failure(self, mock_list, mock_capture):
        mock_list.side_effect = RuntimeError("Vitally API unavailable")

        schemas = VitallySource().get_schemas(self._make_config(), team_id=1)

        names = {s.name for s in schemas}
        assert {"Accounts", "Conversations", "Custom_Objects", "Messages"} <= names
        assert not any(s.name.startswith(CUSTOM_OBJECT_SCHEMA_PREFIX) for s in schemas)
        # Unexpected discovery failures are still captured for triage.
        mock_capture.assert_called_once()

    @pytest.mark.parametrize(
        "error_message",
        [
            "401 Client Error: Unauthorized for url: https://firstignite.rest.vitally.io/resources/customObjects?limit=100",
            "403 Client Error: Forbidden for url: https://rest.vitally-eu.io/resources/customObjects?limit=100",
        ],
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.vitally.source.capture_exception")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.vitally.source.list_custom_object_definitions"
    )
    def test_credential_errors_do_not_spam_error_tracking(self, mock_list, mock_capture, error_message):
        # A revoked/invalid token surfaces as a 401/403 during custom object discovery. Static
        # endpoints must still survive, and we must not capture the credential error to error tracking.
        mock_list.side_effect = RuntimeError(error_message)

        schemas = VitallySource().get_schemas(self._make_config(), team_id=1)

        names = {s.name for s in schemas}
        assert {"Accounts", "Conversations", "Custom_Objects", "Messages"} <= names
        assert not any(s.name.startswith(CUSTOM_OBJECT_SCHEMA_PREFIX) for s in schemas)
        mock_capture.assert_not_called()


class TestVitallyNonRetryableErrors:
    @pytest.mark.parametrize(
        "observed_error",
        [
            # US uses a per-customer subdomain, EU a fixed host — both must be recognised.
            "401 Client Error: Unauthorized for url: https://acme.rest.vitally.io/resources/conversations?limit=100",
            "403 Client Error: Forbidden for url: https://acme.rest.vitally.io/resources/organizations?limit=100",
            "401 Client Error: Unauthorized for url: https://rest.vitally-eu.io/resources/users?limit=1",
        ],
    )
    def test_auth_failures_are_non_retryable(self, observed_error):
        non_retryable_errors = VitallySource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "500 Server Error for url: https://acme.rest.vitally.io/resources/conversations",
            "429 Client Error: Too Many Requests for url: https://acme.rest.vitally.io/resources/accounts",
            "Connection aborted: read timeout",
        ],
    )
    def test_transient_errors_remain_retryable(self, other_error):
        non_retryable_errors = VitallySource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)
