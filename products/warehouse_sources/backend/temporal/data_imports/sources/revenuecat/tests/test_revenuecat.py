import json
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest import mock
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat import revenuecat as api_client
from products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.constants import (
    REVENUECAT_API_BASE_URL,
    REVENUECAT_AUTO_WEBHOOK_NAME,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat import (
    RevenueCatResumeConfig,
    revenuecat_api_source,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source"
    ".rest_client.make_tracked_session"
)


def _api_response(items: list | None = None, *, status: int = 200, next_page: str | None = None) -> Response:
    resp = Response()
    resp.status_code = status
    resp.url = f"{REVENUECAT_API_BASE_URL}/projects/proj_test/customers"
    body: dict[str, Any] = {}
    if items is not None:
        body["items"] = items
    body["next_page"] = next_page
    resp._content = json.dumps(body).encode()
    return resp


def _manager(resume: RevenueCatResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[requests.PreparedRequest]:
    """Wire a mock session; capture each request AT PREPARE TIME as a real PreparedRequest.

    Preparing with a real session applies the framework auth and encodes params exactly as they'd
    go on the wire, so tests can assert the outgoing URL and Authorization header.
    """
    session.headers = {}
    real = requests.Session()
    prepared: list[requests.PreparedRequest] = []

    def _prepare(request: Any) -> requests.PreparedRequest:
        p = real.prepare_request(request)
        prepared.append(p)
        return p

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return prepared


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(
    schema_name: str, responses: list[Response], manager: mock.MagicMock, *, project_id: str = "proj_test"
) -> tuple[list[dict[str, Any]], list[requests.PreparedRequest]]:
    with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
        session = MockSession.return_value
        prepared = _wire(session, responses)
        rows = _rows(
            revenuecat_api_source(
                "sk_test", project_id, schema_name, team_id=1, job_id="j", resumable_source_manager=manager
            )
        )
    return rows, prepared


def _query(prepared: requests.PreparedRequest) -> dict[str, list[str]]:
    return parse_qs(urlsplit(cast("str", prepared.url)).query)


def _ok_json_response(payload: dict | list | None = None, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload if payload is not None else {}
    response.raise_for_status = MagicMock()
    return response


def _http_error_response(status_code: int) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.raise_for_status.side_effect = requests.HTTPError(response=response)
    return response


class TestValidateCredentials:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_returns_true_when_projects_list_succeeds(self, mock_session):
        mock_session.return_value.get.return_value = _ok_json_response({"items": []})

        success, error = api_client.validate_credentials("sk_test", project_id=None)

        assert success is True
        assert error is None
        called_url = mock_session.return_value.get.call_args.args[0]
        assert called_url == f"{REVENUECAT_API_BASE_URL}/projects"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_accepts_project_id_found_in_projects_list(self, mock_session):
        # The project check is a membership test against `GET /projects` — the
        # v2 API has no `GET /projects/{id}` endpoint (probing it 404s even for
        # a valid id, which used to fail every connection attempt).
        mock_session.return_value.get.return_value = _ok_json_response({"items": [{"id": "proj_test"}]})

        success, error = api_client.validate_credentials("sk_test", project_id="proj_test")

        assert success is True
        assert error is None
        assert mock_session.return_value.get.call_count == 1
        called_url = mock_session.return_value.get.call_args.args[0]
        assert called_url == f"{REVENUECAT_API_BASE_URL}/projects"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_accepts_bare_project_id_missing_proj_prefix(self, mock_session):
        # Users routinely enter the id shown on the dashboard without its `proj`
        # prefix (e.g. `64dbb3e3`). The prefix is restored before the membership
        # check so the bare id resolves against the real `proj`-prefixed id.
        mock_session.return_value.get.return_value = _ok_json_response({"items": [{"id": "proj64dbb3e3"}]})

        success, error = api_client.validate_credentials("sk_test", project_id="64dbb3e3")

        assert success is True
        assert error is None

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_follows_pagination_when_project_is_on_a_later_page(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _ok_json_response({"items": [{"id": "proj_a"}], "next_page": "/v2/projects?starting_after=proj_a"}),
            _ok_json_response({"items": [{"id": "proj_b"}], "next_page": None}),
        ]

        success, error = api_client.validate_credentials("sk_test", project_id="proj_b")

        assert success is True
        assert error is None
        assert mock_session.return_value.get.call_count == 2

    @parameterized.expand(
        [
            (401, "rejected the API key"),
            (403, "denied"),
            (404, "could not find"),
            (429, "rate-limited"),
            (500, "RevenueCat API error"),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_returns_false_on_http_error(self, status_code, expected_substring, mock_session):
        mock_session.return_value.get.return_value = _http_error_response(status_code)

        success, error = api_client.validate_credentials("sk_test", project_id=None)

        assert success is False
        assert error is not None
        assert expected_substring.lower() in error.lower()

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_returns_false_on_network_error(self, mock_session):
        mock_session.return_value.get.side_effect = requests.ConnectionError("dns fail")

        success, error = api_client.validate_credentials("sk_test", project_id=None)

        assert success is False
        assert error is not None
        assert "Could not reach RevenueCat" in error

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_skips_project_check_when_id_normalizes_to_empty(self, mock_session):
        # A whitespace-only id is truthy as a raw string but empty once trimmed,
        # so it must not trigger a `GET /projects/` with an empty path segment.
        mock_session.return_value.get.return_value = _ok_json_response({"items": []})

        success, error = api_client.validate_credentials("sk_test", project_id="   ")

        assert success is True
        assert error is None
        assert mock_session.return_value.get.call_count == 1

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_fails_open_on_invalid_json_on_projects_list(self, mock_session):
        # If `GET /projects` returns a 200 with an unparseable body, the key is
        # good but we can't run the membership check — accept rather than block.
        bad_list = _ok_json_response({"items": []})
        bad_list.json.side_effect = requests.exceptions.JSONDecodeError("boom", "", 0)
        mock_session.return_value.get.return_value = bad_list

        success, error = api_client.validate_credentials("sk_test", project_id="proj_test")

        assert success is True
        assert error is None


class TestApiSource:
    def test_follows_next_page_until_exhausted(self):
        # Two pages: first returns one row + a relative next_page, second returns one row with no
        # next_page. Yields both rows in order, follows the resolved absolute link, and stops
        # without a third request.
        next_page = "/v2/projects/proj_test/customers?starting_after=cus_1&limit=100"
        rows, prepared = _run(
            "customers",
            [
                _api_response([{"id": "cus_1", "name": "first"}], next_page=next_page),
                _api_response([{"id": "cus_2", "name": "second"}], next_page=None),
            ],
            _manager(),
        )

        assert rows == [{"id": "cus_1", "name": "first"}, {"id": "cus_2", "name": "second"}]
        assert len(prepared) == 2
        # RevenueCat returns next_page as a root-relative path; it must be resolved against the API
        # host before it becomes the next request URL.
        assert (
            prepared[1].url == f"{REVENUECAT_API_BASE_URL}/projects/proj_test/customers?starting_after=cus_1&limit=100"
        )

    def test_first_request_uses_limit_and_bearer_auth(self):
        _rows_, prepared = _run("customers", [_api_response([], next_page=None)], _manager())

        assert prepared[0].method == "GET"
        assert urlsplit(prepared[0].url).path == "/v2/projects/proj_test/customers"
        assert _query(prepared[0])["limit"] == ["100"]
        assert prepared[0].headers["Authorization"] == "Bearer sk_test"

    def test_returns_empty_page_when_items_missing(self):
        # A 200 with no `items` field is a legit empty page (not an error) — terminate cleanly.
        rows, prepared = _run("customers", [_api_response(next_page=None)], _manager())

        assert rows == []
        assert len(prepared) == 1

    def test_skips_non_dict_rows(self):
        rows, _prepared = _run("customers", [_api_response([{"id": "ok"}, "noise", 42], next_page=None)], _manager())

        assert rows == [{"id": "ok"}]

    def test_normalizes_created_at_from_ms_to_seconds(self):
        # `created_at` arrives as a millisecond epoch — divided by 1000 so the partition layer
        # (which treats bare ints as Unix seconds) buckets rows into the correct week.
        rows, _prepared = _run(
            "products", [_api_response([{"id": "p_1", "created_at": 1658399423658}], next_page=None)], _manager()
        )

        assert rows == [{"id": "p_1", "created_at": 1658399423}]

    def test_leaves_created_at_untouched_when_missing(self):
        rows, _prepared = _run("products", [_api_response([{"id": "p_1"}], next_page=None)], _manager())

        assert rows == [{"id": "p_1"}]

    def test_normalizes_only_the_partition_field_for_customers(self):
        # The customer object has no `created_at` — it partitions by `first_seen_at`, so only that
        # field is normalized; `last_seen_at` (not the partition key) keeps its raw ms epoch.
        rows, _prepared = _run(
            "customers",
            [
                _api_response(
                    [{"id": "cus_1", "first_seen_at": 1658399423658, "last_seen_at": 1700000000000}], next_page=None
                )
            ],
            _manager(),
        )

        assert rows == [{"id": "cus_1", "first_seen_at": 1658399423, "last_seen_at": 1700000000000}]

    def test_saves_resume_state_only_after_yielding_and_only_when_pages_remain(self):
        # Checkpoint the resolved next link AFTER a page is yielded (a crash re-yields it, the merge
        # dedupes) and never after the final page — there's nothing left to resume.
        next_page = "/v2/projects/proj_test/customers?starting_after=cus_1&limit=100"
        manager = _manager()
        _run(
            "customers",
            [_api_response([{"id": "cus_1"}], next_page=next_page), _api_response([{"id": "cus_2"}], next_page=None)],
            manager,
        )

        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == RevenueCatResumeConfig(
            endpoint="customers",
            next_url=f"{REVENUECAT_API_BASE_URL}/projects/proj_test/customers?starting_after=cus_1&limit=100",
        )

    def test_resumes_from_saved_next_url(self):
        saved_url = f"{REVENUECAT_API_BASE_URL}/projects/proj_test/customers?starting_after=cus_99&limit=100"
        manager = _manager(RevenueCatResumeConfig(endpoint="customers", next_url=saved_url))

        _rows_, prepared = _run("customers", [_api_response([], next_page=None)], manager)

        assert prepared[0].url == saved_url

    def test_resumes_legacy_starting_after_cursor(self):
        # Pre-framework state stored only the cursor id; reproduce the old resumed first request
        # (`?starting_after=<id>&limit=100`) so an in-flight sync still advances.
        manager = _manager(RevenueCatResumeConfig(endpoint="customers", starting_after="cus_42"))

        _rows_, prepared = _run("customers", [_api_response([], next_page=None)], manager)

        query = _query(prepared[0])
        assert query["starting_after"] == ["cus_42"]
        assert query["limit"] == ["100"]

    def test_ignores_resume_state_saved_by_a_different_endpoint(self):
        # Replaying a products cursor against customers would skip rows, so cross-endpoint state is
        # dropped and the run starts fresh.
        manager = _manager(RevenueCatResumeConfig(endpoint="products", starting_after="prod_10"))

        _rows_, prepared = _run("customers", [_api_response([], next_page=None)], manager)

        query = _query(prepared[0])
        assert "starting_after" not in query
        assert query["limit"] == ["100"]

    def test_normalizes_pasted_project_url_in_request_path(self):
        # A stored value that's actually a pasted dashboard URL must still resolve to the bare
        # project path at sync time.
        _rows_, prepared = _run(
            "customers",
            [_api_response([], next_page=None)],
            _manager(),
            project_id="https://app.revenuecat.com/projects/proj_real/overview",
        )

        assert urlsplit(prepared[0].url).path == "/v2/projects/proj_real/customers"

    def test_restores_missing_proj_prefix_in_request_path(self):
        _rows_, prepared = _run("customers", [_api_response([], next_page=None)], _manager(), project_id="64dbb3e3")

        assert urlsplit(prepared[0].url).path == "/v2/projects/proj64dbb3e3/customers"

    def test_source_response_partitions_customers_on_first_seen_at(self):
        response = revenuecat_api_source(
            "sk_test", "proj_test", "customers", team_id=1, job_id="j", resumable_source_manager=_manager()
        )

        assert response.name == "customers"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "week"
        assert response.partition_keys == ["first_seen_at"]

    def test_auth_error_raises_without_retry(self):
        with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            prepared = _wire(session, [_api_response([], status=401)])
            with pytest.raises(requests.HTTPError):
                _rows(
                    revenuecat_api_source(
                        "sk_test", "proj_test", "customers", team_id=1, job_id="j", resumable_source_manager=_manager()
                    )
                )

        assert len(prepared) == 1


class TestMsToSeconds:
    def test_converts_int_milliseconds_to_seconds(self):
        assert api_client._ms_to_seconds(1658399423658) == 1658399423

    def test_passes_through_non_int_values(self):
        # Defensive: don't mangle nulls, strings, or anything else the API
        # might surprise us with — only ints get the division.
        assert api_client._ms_to_seconds(None) is None
        assert api_client._ms_to_seconds("1658399423658") == "1658399423658"

    def test_does_not_treat_bool_as_int(self):
        # `bool` subclasses `int` in Python, which would silently turn `True`
        # into `0` (1 // 1000). Make sure we don't fall into that trap.
        assert api_client._ms_to_seconds(True) is True
        assert api_client._ms_to_seconds(False) is False


class TestCreateWebhook:
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._find_webhook_integration"
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_creates_webhook_with_authorization_header(self, mock_session, mock_find):
        mock_find.return_value = None
        mock_session.return_value.post.return_value = _ok_json_response({"id": "wh_1"})

        result = api_client.create_webhook(
            "sk_test",
            project_id="proj_test",
            webhook_url="https://example.com/h",
            authorization_header_value="Bearer my-secret",
        )

        assert result.success is True
        # If we don't pass back the auth header value we asked for it as a
        # pending input, so this list should be empty when we supplied one
        # upfront.
        assert result.pending_inputs == []

        post_args = mock_session.return_value.post.call_args
        # `/integrations/webhooks` — plural. The singular path 404s ("Resource
        # not found"), which used to surface as a bogus "could not find the
        # project" error on every webhook setup attempt.
        assert post_args.args[0] == f"{REVENUECAT_API_BASE_URL}/projects/proj_test/integrations/webhooks"
        # Exact body match: `authorization_header` is the API's field name (a
        # `signing_secret` key means something else and gets rejected), and
        # `event_types` is omitted so the integration receives every event
        # type, current and future.
        assert post_args.kwargs["json"] == {
            "name": REVENUECAT_AUTO_WEBHOOK_NAME,
            "url": "https://example.com/h",
            "authorization_header": "Bearer my-secret",
        }

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._find_webhook_integration"
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_treats_existing_webhook_as_success_with_pending_authorization(self, mock_session, mock_find):
        mock_find.return_value = {"id": "wh_existing", "url": "https://example.com/h"}

        result = api_client.create_webhook("sk_test", project_id="proj_test", webhook_url="https://example.com/h")

        assert result.success is True
        assert result.pending_inputs == ["authorization_header"]
        mock_session.return_value.post.assert_not_called()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._find_webhook_integration"
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_updates_existing_webhook_in_place_when_authorization_header_supplied(self, mock_session, mock_find):
        # Binding the header must not delete + recreate the integration —
        # RevenueCat supports in-place updates via a POST to the integration's
        # own path, and recreating would drop deliveries in the gap. The update
        # body must carry the delivery-critical fields (existing name, our url)
        # next to the header so a replace-semantics update can't strand the
        # integration.
        mock_find.return_value = {"id": "wh_existing", "url": "https://example.com/h", "name": "My custom hook"}
        mock_session.return_value.post.return_value = _ok_json_response({"id": "wh_existing"})

        result = api_client.create_webhook(
            "sk_test",
            project_id="proj_test",
            webhook_url="https://example.com/h",
            authorization_header_value="Bearer my-secret",
        )

        assert result.success is True
        assert result.pending_inputs == []
        post_args = mock_session.return_value.post.call_args
        assert post_args.args[0] == f"{REVENUECAT_API_BASE_URL}/projects/proj_test/integrations/webhooks/wh_existing"
        assert post_args.kwargs["json"] == {
            "name": "My custom hook",
            "url": "https://example.com/h",
            "authorization_header": "Bearer my-secret",
        }

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._find_webhook_integration"
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_reports_pending_authorization_header_when_not_supplied(self, mock_session, mock_find):
        mock_find.return_value = None
        mock_session.return_value.post.return_value = _ok_json_response({"id": "wh_1"})

        result = api_client.create_webhook("sk_test", project_id="proj_test", webhook_url="https://example.com/h")

        assert result.success is True
        assert result.pending_inputs == ["authorization_header"]
        body = mock_session.return_value.post.call_args.kwargs["json"]
        assert "authorization_header" not in body

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._find_webhook_integration"
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_translates_403_into_permission_error(self, mock_session, mock_find):
        mock_find.return_value = None
        mock_session.return_value.post.return_value = _http_error_response(403)

        result = api_client.create_webhook("sk_test", project_id="proj_test", webhook_url="https://example.com/h")

        assert result.success is False
        assert result.error is not None
        assert "denied" in result.error.lower()


class TestDeleteWebhook:
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._list_webhook_integrations"
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_deletes_matching_webhook(self, mock_session, mock_list):
        mock_list.return_value = [{"id": "wh_1", "url": "https://example.com/h"}]
        mock_session.return_value.delete.return_value = _ok_json_response()

        result = api_client.delete_webhook("sk_test", project_id="proj_test", webhook_url="https://example.com/h")

        assert result.success is True
        called_url = mock_session.return_value.delete.call_args.args[0]
        assert called_url == f"{REVENUECAT_API_BASE_URL}/projects/proj_test/integrations/webhooks/wh_1"

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._list_webhook_integrations"
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_returns_success_when_webhook_not_found(self, mock_session, mock_list):
        # Idempotent delete — missing webhook is treated as already gone, not
        # as a failure to surface to users.
        mock_list.return_value = []

        result = api_client.delete_webhook("sk_test", project_id="proj_test", webhook_url="https://example.com/h")

        assert result.success is True
        mock_session.return_value.delete.assert_not_called()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._list_webhook_integrations"
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_404_on_delete_treated_as_success(self, mock_session, mock_list):
        mock_list.return_value = [{"id": "wh_1", "url": "https://example.com/h"}]
        mock_session.return_value.delete.return_value = _ok_json_response(status_code=404)

        result = api_client.delete_webhook("sk_test", project_id="proj_test", webhook_url="https://example.com/h")

        assert result.success is True


class TestGetExternalWebhookInfo:
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._list_webhook_integrations"
    )
    def test_returns_info_for_matching_webhook(self, mock_list):
        # The integration object names its subscription field `event_types`
        # (lowercase values) — reading the webhook-delivery-payload spelling
        # (`events`) would report no subscribed events for every integration.
        mock_list.return_value = [
            {
                "id": "wh_1",
                "url": "https://example.com/h",
                "event_types": ["initial_purchase", "renewal"],
                "name": "PostHog data warehouse",
                "created_at": 1658399423658,
            }
        ]

        info = api_client.get_external_webhook_info(
            "sk_test", project_id="proj_test", webhook_url="https://example.com/h"
        )

        assert info.exists is True
        assert info.url == "https://example.com/h"
        assert info.enabled_events == ["initial_purchase", "renewal"]
        assert info.status == "enabled"
        assert info.description == "PostHog data warehouse"

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._list_webhook_integrations"
    )
    def test_returns_not_found_when_no_match(self, mock_list):
        mock_list.return_value = [{"id": "wh_1", "url": "https://other.example.com"}]

        info = api_client.get_external_webhook_info(
            "sk_test", project_id="proj_test", webhook_url="https://example.com/h"
        )

        assert info.exists is False


class TestProjectPath:
    def test_combines_project_id_with_suffix(self):
        assert api_client._project_path("proj_test", "/customers") == "/projects/proj_test/customers"


class TestNormalizeProjectId:
    @parameterized.expand(
        [
            ("plain_id", "proj1a2b3c4d", "proj1a2b3c4d"),
            ("leading_and_trailing_whitespace", "  proj1a2b3c4d  ", "proj1a2b3c4d"),
            ("full_https_url", "https://app.revenuecat.com/projects/proj1a2b3c4d", "proj1a2b3c4d"),
            ("url_without_scheme", "app.revenuecat.com/projects/proj1a2b3c4d", "proj1a2b3c4d"),
            ("url_with_trailing_path", "https://app.revenuecat.com/projects/proj1a2b3c4d/overview", "proj1a2b3c4d"),
            ("url_with_query_string", "app.revenuecat.com/projects/proj1a2b3c4d?tab=settings", "proj1a2b3c4d"),
            ("url_with_fragment", "app.revenuecat.com/projects/proj1a2b3c4d#section", "proj1a2b3c4d"),
            ("bare_projects_path_fragment", "projects/proj1a2b3c4d", "proj1a2b3c4d"),
            ("trailing_slash", "proj1a2b3c4d/", "proj1a2b3c4d"),
            ("bare_id_missing_proj_prefix", "1a2b3c4d", "proj1a2b3c4d"),
            ("bare_id_from_url_missing_prefix", "app.revenuecat.com/projects/1a2b3c4d", "proj1a2b3c4d"),
            ("bare_id_with_whitespace_missing_prefix", "  1a2b3c4d  ", "proj1a2b3c4d"),
            ("none", None, ""),
            ("empty", "", ""),
            ("whitespace_only", "   ", ""),
        ]
    )
    def test_normalizes(self, _name, raw, expected):
        assert api_client._normalize_project_id(raw) == expected


class TestAccessibleProjectIds:
    def test_extracts_ids_in_order(self):
        payload = {"items": [{"id": "proj_a", "name": "A"}, {"id": "proj_b"}]}

        assert api_client._accessible_project_ids(payload) == ["proj_a", "proj_b"]

    @parameterized.expand(
        [
            ("empty_items", {"items": []}),
            ("missing_items", {}),
            ("none_payload", None),
            ("items_not_a_list", {"items": "nope"}),
            ("rows_missing_id", {"items": [{"name": "A"}, "noise", 42]}),
        ]
    )
    def test_returns_empty_for_unusable_payloads(self, _name, payload):
        assert api_client._accessible_project_ids(payload) == []


class TestValidateCredentialsProjectSuggestions:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_miss_lists_single_accessible_project(self, mock_session):
        # The key works (it can list projects) but the entered id doesn't exist.
        # The error should name the one project the key can actually reach.
        mock_session.return_value.get.return_value = _ok_json_response(
            {"items": [{"id": "proj_real", "name": "My App"}]}
        )

        success, error = api_client.validate_credentials("sk_test", project_id="proj_typo")

        assert success is False
        assert error is not None
        assert "proj_typo" in error
        assert "proj_real" in error
        # Project names are deliberately never surfaced (they land in analytics).
        assert "My App" not in error

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_miss_lists_multiple_accessible_projects(self, mock_session):
        mock_session.return_value.get.return_value = _ok_json_response({"items": [{"id": "proj_a"}, {"id": "proj_b"}]})

        success, error = api_client.validate_credentials("sk_test", project_id="proj_typo")

        assert success is False
        assert error is not None
        assert "proj_a" in error and "proj_b" in error

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_miss_with_no_accessible_projects_falls_back_to_generic_message(self, mock_session):
        mock_session.return_value.get.return_value = _ok_json_response({"items": []})

        success, error = api_client.validate_credentials("sk_test", project_id="proj_typo")

        assert success is False
        assert error is not None
        assert "could not find" in error.lower()

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_normalizes_pasted_url_before_checking_project(self, mock_session):
        # A user pastes the whole dashboard URL — the bare id pulled out of it
        # must match against the accessible-projects list.
        mock_session.return_value.get.return_value = _ok_json_response({"items": [{"id": "proj_real"}]})

        success, error = api_client.validate_credentials(
            "sk_test", project_id="https://app.revenuecat.com/projects/proj_real/overview"
        )

        assert success is True
        assert error is None
