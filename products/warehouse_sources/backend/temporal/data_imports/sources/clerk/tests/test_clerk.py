import json
import dataclasses
from typing import Any

import pytest
from unittest.mock import MagicMock

from requests import Response
from requests.exceptions import HTTPError, RequestException
from structlog.testing import capture_logs

from products.warehouse_sources.backend.temporal.data_imports.sources.clerk.clerk import (
    ClerkPaginator,
    ClerkResumeConfig,
    _convert_timestamps,
    _strip_sensitive_fields,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clerk.settings import (
    CLERK_ENDPOINTS,
    RETIRED_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clerk.source import ClerkSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clerk import ClerkSourceConfig


class TestClerkPaginator:
    @pytest.mark.parametrize(
        ("label", "response_body", "has_next", "expected_offset"),
        [
            ("direct_array_full_page", [{"id": f"u{i}"} for i in range(100)], True, 100),
            ("direct_array_partial_page", [{"id": "u1"}, {"id": "u2"}], False, 0),
            ("wrapped_full_page", {"data": [{"id": f"o{i}"} for i in range(100)], "total_count": 250}, True, 100),
            # total_count exactly divisible by limit: skip the extra empty request.
            (
                "wrapped_full_terminal_page",
                {"data": [{"id": f"o{i}"} for i in range(100)], "total_count": 100},
                False,
                0,
            ),
            ("wrapped_partial_page", {"data": [{"id": "o1"}], "total_count": 1}, False, 0),
            ("empty_body", None, False, 0),
            ("empty_dict", {}, False, 0),
        ],
    )
    def test_update_state(self, label: str, response_body: Any, has_next: bool, expected_offset: int) -> None:
        paginator = ClerkPaginator(limit=100)
        response = MagicMock()
        response.json.return_value = response_body
        paginator.update_state(response)
        assert paginator._has_next_page is has_next
        assert paginator._offset == expected_offset

    def test_update_state_stops_on_empty_body(self) -> None:
        # A 2xx response with an empty body must stop pagination, not crash on
        # response.json() (Clerk returns this and it reached update_state raw).
        response = Response()
        response.status_code = 200
        response._content = b""
        paginator = ClerkPaginator(limit=100)

        paginator.update_state(response)

        assert paginator.has_next_page is False
        assert paginator._offset == 0

    @pytest.mark.parametrize(
        ("label", "response_body", "has_next", "expected_offset"),
        [
            ("full_page", {"m2m_tokens": [{"id": f"mt{i}"} for i in range(100)], "total_count": 250}, True, 100),
            ("terminal_page", {"m2m_tokens": [{"id": "mt1"}], "total_count": 1}, False, 0),
            # Reading the default `data` key here would see zero rows and stop after page one.
            ("wrong_key_is_not_read", {"data": [{"id": f"mt{i}"} for i in range(100)]}, False, 0),
        ],
    )
    def test_update_state_with_custom_data_key(
        self, label: str, response_body: Any, has_next: bool, expected_offset: int
    ) -> None:
        paginator = ClerkPaginator(limit=100, data_key="m2m_tokens")
        response = MagicMock()
        response.json.return_value = response_body

        paginator.update_state(response)

        assert paginator._has_next_page is has_next
        assert paginator._offset == expected_offset


# ``users``/``invitations`` return direct arrays; ``organizations``/``organization_memberships``
# return ``{data: [...], total_count: N}`` wrapped responses. Both flavours share the same
# paginator semantics; the only behavioural difference is how rest_source extracts rows.
_DIRECT_ARRAY_ENDPOINT = "users"
_WRAPPED_ENDPOINT = "organizations"


def _full_page(endpoint: str, prefix: str) -> Any:
    items = [{"id": f"{prefix}{i}"} for i in range(100)]
    if endpoint == _WRAPPED_ENDPOINT:
        return {"data": items, "total_count": 9999}
    return items


def _partial_page(endpoint: str, ids: list[str]) -> Any:
    items = [{"id": i} for i in ids]
    if endpoint == _WRAPPED_ENDPOINT:
        return {"data": items, "total_count": len(items)}
    return items


def _driver() -> SourceDriver:
    return SourceDriver(ClerkSource(), ClerkSourceConfig(secret_key="sk_live_test"))


class TestClerkSourceResumeBehavior:
    """End-to-end resume behaviour through the shared ``rest_api_resource`` path."""

    @pytest.mark.parametrize("endpoint", [_DIRECT_ARRAY_ENDPOINT, _WRAPPED_ENDPOINT])
    def test_fresh_run_saves_offset_after_each_non_terminal_page(self, endpoint: str) -> None:
        responses = [
            ScriptedResponse(json=_full_page(endpoint, "a")),
            ScriptedResponse(json=_full_page(endpoint, "b")),
            ScriptedResponse(json=_partial_page(endpoint, ["c1", "c2"])),
        ]
        result = _driver().run(endpoint, responses)

        # First request omits offset (fresh run); subsequent requests include it.
        assert result.params("offset") == [None, "100", "200"]

        assert result.saved_states == [
            ClerkResumeConfig(offset=100),
            ClerkResumeConfig(offset=200),
        ]
        assert result.raised is None

    @pytest.mark.parametrize("endpoint", [_DIRECT_ARRAY_ENDPOINT, _WRAPPED_ENDPOINT])
    def test_resume_seeds_paginator_with_saved_offset(self, endpoint: str) -> None:
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json=_partial_page(endpoint, ["c1", "c2"]))],
            resume_state=ClerkResumeConfig(offset=200),
        )

        # The very first request goes out at the resumed offset — no initial
        # offset-less call to re-fetch the already-synced pages.
        assert result.params("offset") == ["200"]
        assert result.raised is None

    @pytest.mark.parametrize(
        "cfg",
        [
            ClerkResumeConfig(offset=1500),
            ClerkResumeConfig(
                fan_out={"completed": ["/sessions?user_id=user_1"], "current": None, "child_state": None}
            ),
        ],
    )
    def test_resume_config_serialization_round_trip(self, cfg: ClerkResumeConfig) -> None:
        as_json = json.dumps(dataclasses.asdict(cfg))
        reconstituted = ClerkResumeConfig(**json.loads(as_json))
        assert reconstituted == cfg


class TestClerkEndpoints:
    @pytest.mark.parametrize(
        ("endpoint", "path"),
        [
            # Clerk renamed these from /commerce/... to /billing/...; the old path now answers
            # 400 Bad Request instead of serving the list.
            ("commerce_plans", "/billing/plans"),
            ("commerce_subscription_items", "/billing/subscription_items"),
        ],
    )
    def test_commerce_endpoints_use_the_renamed_billing_path(self, endpoint: str, path: str) -> None:
        assert CLERK_ENDPOINTS[endpoint].path == path

    @pytest.mark.parametrize(
        "item",
        [
            # sessions
            {"created_at": 1700000000000, "expire_at": 1700000600000, "abandon_at": None},
            # api_keys / m2m_tokens
            {"created_at": 1700000000000, "expiration": 1700000600000, "last_used_at": 1700000300000},
            # commerce_subscription_items
            {"period_start": 1700000000000, "period_end": 1700000600000, "ended_at": 1700000300000},
            # saml_connections
            {"idp_certificate_issued_at": 1700000000000, "idp_certificate_expires_at": 1700000600000},
        ],
    )
    def test_millisecond_timestamps_are_converted_to_seconds(self, item: dict[str, Any]) -> None:
        # Left unconverted these land ~1000x in the future, which breaks the datetime partitioning
        # the source declares on created_at.
        converted = _convert_timestamps(dict(item))

        for field, value in item.items():
            assert converted[field] == (value // 1000 if value is not None else None)

    @pytest.mark.parametrize(
        "item,paths,expected",
        [
            # top-level redeemable link on invitations / organization_invitations
            (
                {"id": "inv_1", "email_address": "a@b.com", "url": "https://clerk.example/accept?ticket=secret"},
                ("url",),
                {"id": "inv_1", "email_address": "a@b.com"},
            ),
            # nested link on waitlist_entries
            (
                {"id": "wl_1", "invitation": {"id": "inv_2", "url": "https://clerk.example/accept?ticket=secret"}},
                ("invitation.url",),
                {"id": "wl_1", "invitation": {"id": "inv_2"}},
            ),
            # nested field absent (no invitation was sent) — nothing to strip, no crash
            (
                {"id": "wl_1", "invitation": None},
                ("invitation.url",),
                {"id": "wl_1", "invitation": None},
            ),
        ],
    )
    def test_sensitive_url_fields_are_stripped(
        self, item: dict[str, Any], paths: tuple[str, ...], expected: dict[str, Any]
    ) -> None:
        # Redeemable invitation links must never reach the warehouse table, where any viewer
        # could copy one and accept the invitation.
        assert _strip_sensitive_fields(dict(item), paths) == expected


class TestClerkFilteredEndpoints:
    """Clerk rejects `/sessions` and `/m2m_tokens` unless the request carries a parent filter."""

    @pytest.mark.parametrize(
        ("endpoint", "parent_path", "parent_page", "parent_id", "child_page"),
        [
            ("sessions", "/users", [{"id": "user_1"}], "user_1", [{"id": "sess_1"}]),
            (
                "m2m_tokens",
                "/machines",
                {"data": [{"id": "mch_1"}], "total_count": 1},
                "mch_1",
                {"m2m_tokens": [{"id": "mt_1"}], "total_count": 1},
            ),
        ],
    )
    def test_endpoint_is_filtered_by_its_parent(
        self,
        endpoint: str,
        parent_path: str,
        parent_page: Any,
        parent_id: str,
        child_page: Any,
    ) -> None:
        # Unfiltered, Clerk answers 422 (`/sessions`) or 400 (`/m2m_tokens`) and the sync dies.
        config = CLERK_ENDPOINTS[endpoint]
        assert config.fan_out is not None
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json=parent_page), ScriptedResponse(json=child_page)],
        )

        assert result.paths == [f"/v1{parent_path}", f"/v1{config.path}"]
        assert [request.origin for request in result.requests] == ["https://api.clerk.com"] * 2
        assert result.params("limit") == ["100", "100"]
        # The resolve placeholder must not leak into the query params as well.
        assert result.requests[1].query[config.fan_out.query_param] == (parent_id,)
        expected_rows = child_page["m2m_tokens"] if endpoint == "m2m_tokens" else child_page
        assert result.rows == expected_rows
        # Fan-out state is per parent, not a flat offset — a retry must not restart the walk.
        saved = result.saved_states[-1]
        assert saved.fan_out == {
            "completed": [f"{config.path}?{config.fan_out.query_param}={parent_id}"],
            "current": None,
            "child_state": None,
        }
        assert result.raised is None


class TestClerkFeatureGatedEndpoints:
    @pytest.mark.parametrize(
        ("endpoint", "status_code", "body"),
        [
            ("allowlist_identifiers", 402, {"errors": [{"code": "payment_required"}]}),
            ("blocklist_identifiers", 402, {"errors": [{"code": "payment_required"}]}),
            ("commerce_plans", 400, {"errors": [{"code": "billing_not_enabled"}]}),
            ("commerce_subscription_items", 400, {"errors": [{"code": "billing_not_enabled"}]}),
            ("commerce_plans", 403, {"errors": [{"code": "feature_not_enabled"}]}),
            # Restrictions off: the allow-list endpoint answers 404 resource_not_found, not a 4xx code.
            ("allowlist_identifiers", 404, {"errors": [{"code": "resource_not_found"}]}),
            # OAuth applications off: the list endpoint answers the same 404 resource_not_found.
            ("oauth_applications", 404, {"errors": [{"code": "resource_not_found"}]}),
            # Domains feature off: the list endpoint answers the same 404 resource_not_found.
            ("domains", 404, {"errors": [{"code": "resource_not_found"}]}),
            # Organizations off: the invitations list answers the same 404 resource_not_found.
            ("organization_invitations", 404, {"errors": [{"code": "resource_not_found"}]}),
            # Organizations off: every other instance-wide Organizations list answers it too.
            ("organizations", 404, {"errors": [{"code": "resource_not_found"}]}),
            ("organization_memberships", 404, {"errors": [{"code": "resource_not_found"}]}),
            ("organization_domains", 404, {"errors": [{"code": "resource_not_found"}]}),
            ("organization_roles", 404, {"errors": [{"code": "resource_not_found"}]}),
            ("organization_permissions", 404, {"errors": [{"code": "resource_not_found"}]}),
            # Invitations unavailable: the list answers the same 404 resource_not_found.
            ("invitations", 404, {"errors": [{"code": "resource_not_found"}]}),
            # SMS off: the SMS template list answers the same 404 resource_not_found.
            ("sms_templates", 404, {"errors": [{"code": "resource_not_found"}]}),
            # Machine (M2M) auth off: the machines list answers the same 404 resource_not_found.
            ("machines", 404, {"errors": [{"code": "resource_not_found"}]}),
            # m2m_tokens fans out over /machines, so it meets the same 404 on its parent fetch.
            ("m2m_tokens", 404, {"errors": [{"code": "resource_not_found"}]}),
        ],
    )
    def test_feature_not_enabled_syncs_no_rows_instead_of_failing(
        self, endpoint: str, status_code: int, body: dict[str, Any]
    ) -> None:
        with capture_logs() as logs:
            result = _driver().run(endpoint, [ScriptedResponse(status=status_code, json=body)])

        assert result.rows == []
        assert result.raised is None
        assert any(CLERK_ENDPOINTS[endpoint].gated_feature in log["event"] for log in logs)

    @pytest.mark.parametrize(
        ("endpoint", "status_code", "body"),
        [
            # A gated endpoint failing for an unrelated reason must still fail the sync.
            ("commerce_plans", 400, {"errors": [{"code": "invalid_request"}]}),
            # A 404 with an unrelated code is a real failure, not the feature-off signal.
            ("allowlist_identifiers", 404, {"errors": [{"code": "invalid_request"}]}),
            # A table with no feature gate never swallows an error.
            ("users", 402, {"errors": [{"code": "payment_required"}]}),
        ],
    )
    def test_other_errors_still_fail_the_sync(self, endpoint: str, status_code: int, body: dict[str, Any]) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(status=status_code, json=body)])
        assert isinstance(result.raised, HTTPError)


class TestClerkRetiredEndpoints:
    @pytest.mark.parametrize("endpoint", sorted(RETIRED_ENDPOINTS))
    def test_retired_endpoint_is_off_the_catalog_and_explains_itself(self, endpoint: str) -> None:
        # Discovery drops the table because it left CLERK_ENDPOINTS; a job already in flight has
        # to say why rather than blow up on a missing key.
        assert endpoint not in CLERK_ENDPOINTS

        result = _driver().run(endpoint, [])
        assert isinstance(result.raised, ValueError)
        assert "Turn off syncing for this table" in str(result.raised)
        assert result.requests == []


class TestClerkValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_substring"),
        [
            (400, "invalid or has been revoked"),
            (401, "invalid or has been revoked"),
            (403, "active Clerk instance"),
            (404, "active Clerk instance"),
            (500, "Couldn't validate your Clerk secret key"),
        ],
    )
    def test_maps_status_to_curated_message_without_leaking_raw_body(
        self, status_code: int, expected_substring: str
    ) -> None:
        # A regression that forwards Clerk's response body (or errors[0].message) back to the wizard
        # would surface this sentinel; the curated copy must not.
        sentinel = "RAW-CLERK-BODY-SENTINEL"
        response = ScriptedResponse(status=status_code, json={"errors": [{"message": sentinel}]})
        script = always(response) if status_code == 500 else [response]
        with scripted_network(script) as network:
            is_valid, message = validate_credentials("sk_test_key")
        assert is_valid is False
        assert expected_substring in (message or "")
        assert sentinel not in (message or "")
        assert network.requests_log[0].path == "/v1/users"
        assert network.requests_log[0].param("limit") == "1"

    @pytest.mark.parametrize("secret_key", ["sk_live_\u200bkey", "sk_live_\u3042key"])
    def test_non_ascii_key_is_rejected_before_any_request(self, secret_key: str) -> None:
        # Such a key can't be encoded into the Authorization header, so dispatching the request
        # raises UnicodeEncodeError; the guard must catch it first and explain what to do.
        with scripted_network([]) as network:
            is_valid, message = validate_credentials(secret_key)
        assert is_valid is False
        assert "Copy the key again" in (message or "")
        assert "latin-1" not in (message or "")
        assert network.requests_log == []

    @pytest.mark.parametrize("secret_key", ["sk_live_key\rextra_pasted_content", "sk_live_key\nextra_pasted_content"])
    def test_key_with_return_character_is_rejected_before_any_request(self, secret_key: str) -> None:
        # A carriage return or newline is ASCII, so it passes isascii(), but requests still rejects
        # it as an invalid header value (InvalidHeader) when dispatching. That exception is a
        # RequestException subclass, so it was previously swallowed by the generic network-error
        # handler below and reported as a transient "couldn't reach Clerk" failure instead of
        # explaining the malformed key.
        with scripted_network([]) as network:
            is_valid, message = validate_credentials(secret_key)
        assert is_valid is False
        assert "Copy the key again" in (message or "")
        assert network.requests_log == []

    def test_network_error_returns_actionable_message_without_leaking_exception(self) -> None:
        def fail_request(_request: Any) -> ScriptedResponse:
            raise RequestException("connection reset by peer")

        with scripted_network(fail_request) as network:
            is_valid, message = validate_credentials("sk_test_key")
        assert is_valid is False
        assert "Couldn't reach Clerk" in (message or "")
        assert "connection reset by peer" not in (message or "")
        assert network.requests_log[0].path == "/v1/users"
