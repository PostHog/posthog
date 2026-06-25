from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat import revenuecat as api_client
from products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.constants import (
    REVENUECAT_API_BASE_URL,
    REVENUECAT_AUTO_WEBHOOK_NAME,
    REVENUECAT_WEBHOOK_EVENT_TYPES,
)


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


class TestIterateListEndpoint:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_follows_next_page_until_exhausted(self, mock_session):
        # Two pages: first returns one row + a relative next_page, second
        # returns one row with no next_page. The iterator should yield both
        # rows in order and stop without making a third call.
        first = _ok_json_response(
            {
                "items": [{"id": "cus_1", "name": "first"}],
                "next_page": "/v2/projects/proj_test/customers?starting_after=cus_1&limit=100",
            }
        )
        second = _ok_json_response({"items": [{"id": "cus_2", "name": "second"}], "next_page": None})
        mock_session.return_value.get.side_effect = [first, second]

        rows = list(
            api_client.iterate_list_endpoint(
                "sk_test",
                project_id="proj_test",
                path_suffix="/customers",
                endpoint_name="customers",
            )
        )

        assert rows == [{"id": "cus_1", "name": "first"}, {"id": "cus_2", "name": "second"}]
        assert mock_session.return_value.get.call_count == 2

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_invokes_on_cursor_advance_with_last_row_id_per_page(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _ok_json_response(
                {
                    "items": [{"id": "cus_1"}, {"id": "cus_2"}],
                    "next_page": "/v2/projects/proj_test/customers?starting_after=cus_2",
                }
            ),
            _ok_json_response({"items": [{"id": "cus_3"}], "next_page": None}),
        ]
        seen: list[tuple[str, str]] = []

        list(
            api_client.iterate_list_endpoint(
                "sk_test",
                project_id="proj_test",
                path_suffix="/customers",
                endpoint_name="customers",
                on_cursor_advance=lambda name, last_id: seen.append((name, last_id)),
            )
        )

        # Saved after each page's last row — never before, otherwise a crash
        # would skip the page rather than re-yield it (merge dedupes on PK).
        assert seen == [("customers", "cus_2"), ("customers", "cus_3")]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_uses_starting_after_when_resuming(self, mock_session):
        mock_session.return_value.get.return_value = _ok_json_response({"items": [], "next_page": None})

        list(
            api_client.iterate_list_endpoint(
                "sk_test",
                project_id="proj_test",
                path_suffix="/customers",
                endpoint_name="customers",
                starting_after="cus_42",
            )
        )

        called_params = mock_session.return_value.get.call_args.kwargs["params"]
        assert called_params["starting_after"] == "cus_42"
        assert called_params["limit"] == api_client.DEFAULT_PAGE_SIZE

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_returns_immediately_when_items_missing(self, mock_session):
        # Defensive: a 200 with no `items` field should be treated as an empty
        # page rather than crashing on `None.append`.
        mock_session.return_value.get.return_value = _ok_json_response({"next_page": None})

        rows = list(
            api_client.iterate_list_endpoint(
                "sk_test", project_id="proj_test", path_suffix="/customers", endpoint_name="customers"
            )
        )

        assert rows == []

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_skips_non_dict_rows(self, mock_session):
        mock_session.return_value.get.return_value = _ok_json_response(
            {"items": [{"id": "ok"}, "noise", 42], "next_page": None}
        )

        rows = list(
            api_client.iterate_list_endpoint(
                "sk_test", project_id="proj_test", path_suffix="/customers", endpoint_name="customers"
            )
        )

        assert rows == [{"id": "ok"}]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_normalizes_created_at_from_ms_to_seconds(self, mock_session):
        # `created_at` comes back from RevenueCat as a millisecond epoch — we
        # divide by 1000 so the partition layer (which treats bare ints as Unix
        # seconds) buckets rows into the correct week.
        mock_session.return_value.get.return_value = _ok_json_response(
            {"items": [{"id": "cus_1", "created_at": 1658399423658}], "next_page": None}
        )

        rows = list(
            api_client.iterate_list_endpoint(
                "sk_test", project_id="proj_test", path_suffix="/customers", endpoint_name="customers"
            )
        )

        assert rows == [{"id": "cus_1", "created_at": 1658399423}]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_leaves_created_at_untouched_when_missing(self, mock_session):
        mock_session.return_value.get.return_value = _ok_json_response({"items": [{"id": "cus_1"}], "next_page": None})

        rows = list(
            api_client.iterate_list_endpoint(
                "sk_test", project_id="proj_test", path_suffix="/customers", endpoint_name="customers"
            )
        )

        assert rows == [{"id": "cus_1"}]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_normalizes_configured_timestamp_field(self, mock_session):
        # The customer object has no `created_at` — it partitions by
        # `first_seen_at`, so that's the field that must be normalized to seconds.
        mock_session.return_value.get.return_value = _ok_json_response(
            {
                "items": [{"id": "cus_1", "first_seen_at": 1658399423658, "last_seen_at": 1700000000000}],
                "next_page": None,
            }
        )

        rows = list(
            api_client.iterate_list_endpoint(
                "sk_test",
                project_id="proj_test",
                path_suffix="/customers",
                endpoint_name="customers",
                timestamp_fields=("first_seen_at",),
            )
        )

        # `first_seen_at` is normalized; `last_seen_at` (not the partition key) is
        # left as the raw ms epoch.
        assert rows == [{"id": "cus_1", "first_seen_at": 1658399423, "last_seen_at": 1700000000000}]


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
    def test_creates_webhook_with_all_known_event_types(self, mock_session, mock_find):
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

        post_kwargs = mock_session.return_value.post.call_args.kwargs
        body = post_kwargs["json"]
        assert body["url"] == "https://example.com/h"
        assert body["name"] == REVENUECAT_AUTO_WEBHOOK_NAME
        assert set(body["events"]) == set(REVENUECAT_WEBHOOK_EVENT_TYPES)
        assert body["signing_secret"] == "Bearer my-secret"

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
    def test_fails_when_existing_webhook_and_new_authorization_header_supplied(self, mock_session, mock_find):
        # RevenueCat has no in-place update for the auth header. If a webhook
        # already exists and we're asked to bind a new header, fail loudly so
        # the caller knows to delete + recreate explicitly — silently keeping
        # the existing webhook would leave it bound to a stale header value.
        mock_find.return_value = {"id": "wh_existing", "url": "https://example.com/h"}

        result = api_client.create_webhook(
            "sk_test",
            project_id="proj_test",
            webhook_url="https://example.com/h",
            authorization_header_value="Bearer my-secret",
        )

        assert result.success is False
        assert result.error is not None
        assert "already exists" in result.error.lower()
        mock_session.return_value.post.assert_not_called()

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
        assert called_url == f"{REVENUECAT_API_BASE_URL}/projects/proj_test/integrations/webhook/wh_1"

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
        mock_list.return_value = [
            {
                "id": "wh_1",
                "url": "https://example.com/h",
                "events": ["INITIAL_PURCHASE", "RENEWAL"],
                "name": "PostHog data warehouse",
                "created_at": 1658399423658,
            }
        ]

        info = api_client.get_external_webhook_info(
            "sk_test", project_id="proj_test", webhook_url="https://example.com/h"
        )

        assert info.exists is True
        assert info.url == "https://example.com/h"
        assert info.enabled_events == ["INITIAL_PURCHASE", "RENEWAL"]
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


class TestIterateListEndpointNormalization:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_normalizes_project_id_in_request_url(self, mock_session):
        # A stored value that's actually a pasted URL must still resolve to the
        # bare project path during sync.
        mock_session.return_value.get.return_value = _ok_json_response({"items": [], "next_page": None})

        list(
            api_client.iterate_list_endpoint(
                "sk_test",
                project_id="https://app.revenuecat.com/projects/proj_real",
                path_suffix="/customers",
                endpoint_name="customers",
            )
        )

        called_url = mock_session.return_value.get.call_args.args[0]
        assert called_url == f"{REVENUECAT_API_BASE_URL}/projects/proj_real/customers"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.revenuecat._session")
    def test_restores_missing_proj_prefix_in_request_url(self, mock_session):
        # A source stored with a bare id must hit the `proj`-prefixed path at
        # sync time, matching what validation accepted.
        mock_session.return_value.get.return_value = _ok_json_response({"items": [], "next_page": None})

        list(
            api_client.iterate_list_endpoint(
                "sk_test",
                project_id="64dbb3e3",
                path_suffix="/customers",
                endpoint_name="customers",
            )
        )

        called_url = mock_session.return_value.get.call_args.args[0]
        assert called_url == f"{REVENUECAT_API_BASE_URL}/projects/proj64dbb3e3/customers"
