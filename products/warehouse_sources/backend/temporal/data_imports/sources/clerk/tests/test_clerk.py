import json
import dataclasses
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response
from requests.exceptions import HTTPError, RequestException

from products.warehouse_sources.backend.temporal.data_imports.sources.clerk.clerk import (
    ClerkPaginator,
    ClerkResumeConfig,
    _convert_timestamps,
    _strip_sensitive_fields,
    clerk_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clerk.settings import (
    CLERK_ENDPOINTS,
    RETIRED_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


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


def _make_http_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


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


def _drive(
    endpoint: str, manager: MagicMock, responses: list[Response], logger: Any = None
) -> list[tuple[str, dict[str, Any]]]:
    """Drive ``clerk_source`` against a mocked HTTP session, returning the (url, params)
    of each request sent. Params are shallow copies — the paginator mutates the underlying
    Request in-place between pages."""
    sent: list[tuple[str, dict[str, Any]]] = []
    response_iter = iter(responses)

    def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
        sent.append((request.url, dict(request.params)))
        return next(response_iter)

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
    ) as MockSession:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.side_effect = lambda req: req
        mock_session.send.side_effect = fake_send

        source_response = clerk_source(
            secret_key="sk_live_test",
            endpoint=endpoint,
            team_id=123,
            job_id="test_job",
            resumable_source_manager=manager,
            logger=logger if logger is not None else MagicMock(),
        )
        list(cast(Iterable[Any], source_response.items()))
        return sent


class TestClerkSourceResumeBehavior:
    """End-to-end resume behaviour through the shared ``rest_api_resource`` path."""

    def _drive(self, endpoint: str, manager: MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
        return [params for _url, params in _drive(endpoint, manager, responses)]

    @pytest.mark.parametrize("endpoint", [_DIRECT_ARRAY_ENDPOINT, _WRAPPED_ENDPOINT])
    def test_fresh_run_saves_offset_after_each_non_terminal_page(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(_full_page(endpoint, "a")),
            _make_http_response(_full_page(endpoint, "b")),
            _make_http_response(_partial_page(endpoint, ["c1", "c2"])),
        ]
        sent_params = self._drive(endpoint, manager, responses)

        # First request omits offset (fresh run); subsequent requests include it.
        assert [p.get("offset") for p in sent_params] == [None, 100, 200]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            ClerkResumeConfig(offset=100),
            ClerkResumeConfig(offset=200),
        ]

    @pytest.mark.parametrize("endpoint", [_DIRECT_ARRAY_ENDPOINT, _WRAPPED_ENDPOINT])
    def test_resume_seeds_paginator_with_saved_offset(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = ClerkResumeConfig(offset=200)

        responses = [
            _make_http_response(_partial_page(endpoint, ["c1", "c2"])),
        ]
        sent_params = self._drive(endpoint, manager, responses)

        # The very first request goes out at the resumed offset — no initial
        # offset-less call to re-fetch the already-synced pages.
        assert [p.get("offset") for p in sent_params] == [200]

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
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        sent = _drive(
            endpoint,
            manager,
            [_make_http_response(parent_page), _make_http_response(child_page)],
        )

        assert [url for url, _params in sent] == [
            f"https://api.clerk.com/v1{parent_path}",
            f"https://api.clerk.com/v1{config.path}?{config.fan_out.query_param}={parent_id}",
        ]
        # The resolve placeholder must not leak into the query params as well.
        assert config.fan_out.query_param not in sent[1][1]
        # Fan-out state is per parent, not a flat offset — a retry must not restart the walk.
        saved = manager.save_state.call_args.args[0]
        assert saved.fan_out == {
            "completed": [f"{config.path}?{config.fan_out.query_param}={parent_id}"],
            "current": None,
            "child_state": None,
        }


class TestClerkFeatureGatedEndpoints:
    def _drive_with_error(self, endpoint: str, error_response: Response, logger: Any) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        _drive(endpoint, manager, [error_response], logger=logger)

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
        logger = MagicMock()

        self._drive_with_error(endpoint, _make_http_response(body, status_code=status_code), logger)

        assert CLERK_ENDPOINTS[endpoint].gated_feature in logger.warning.call_args.args[0]

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
        with pytest.raises(HTTPError):
            self._drive_with_error(endpoint, _make_http_response(body, status_code=status_code), MagicMock())


class TestClerkRetiredEndpoints:
    @pytest.mark.parametrize("endpoint", sorted(RETIRED_ENDPOINTS))
    def test_retired_endpoint_is_off_the_catalog_and_explains_itself(self, endpoint: str) -> None:
        # Discovery drops the table because it left CLERK_ENDPOINTS; a job already in flight has
        # to say why rather than blow up on a missing key.
        assert endpoint not in CLERK_ENDPOINTS

        manager = MagicMock(spec=ResumableSourceManager)
        with pytest.raises(ValueError, match="Turn off syncing for this table"):
            clerk_source(
                secret_key="sk_live_test",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                logger=MagicMock(),
            )


_CLERK_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.clerk.clerk"
_VALIDATE_SESSION = f"{_CLERK_MODULE}.make_tracked_session"


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
        response = _make_http_response({"errors": [{"message": sentinel}]}, status_code=status_code)
        with patch(_VALIDATE_SESSION) as mock_session:
            mock_session.return_value.get.return_value = response
            is_valid, message = validate_credentials("sk_test_key")
        assert is_valid is False
        assert expected_substring in (message or "")
        assert sentinel not in (message or "")

    @pytest.mark.parametrize("secret_key", ["sk_live_\u200bkey", "sk_live_\u3042key"])
    def test_non_ascii_key_is_rejected_before_any_request(self, secret_key: str) -> None:
        # Such a key can't be encoded into the Authorization header, so dispatching the request
        # raises UnicodeEncodeError; the guard must catch it first and explain what to do.
        with patch(_VALIDATE_SESSION) as mock_session:
            is_valid, message = validate_credentials(secret_key)
        assert is_valid is False
        assert "Copy the key again" in (message or "")
        assert "latin-1" not in (message or "")
        mock_session.assert_not_called()

    @pytest.mark.parametrize("secret_key", ["sk_live_key\rextra_pasted_content", "sk_live_key\nextra_pasted_content"])
    def test_key_with_return_character_is_rejected_before_any_request(self, secret_key: str) -> None:
        # A carriage return or newline is ASCII, so it passes isascii(), but requests still rejects
        # it as an invalid header value (InvalidHeader) when dispatching. That exception is a
        # RequestException subclass, so it was previously swallowed by the generic network-error
        # handler below and reported as a transient "couldn't reach Clerk" failure instead of
        # explaining the malformed key.
        with patch(_VALIDATE_SESSION) as mock_session:
            is_valid, message = validate_credentials(secret_key)
        assert is_valid is False
        assert "Copy the key again" in (message or "")
        mock_session.assert_not_called()

    def test_network_error_returns_actionable_message_without_leaking_exception(self) -> None:
        with patch(_VALIDATE_SESSION) as mock_session:
            mock_session.return_value.get.side_effect = RequestException("connection reset by peer")
            is_valid, message = validate_credentials("sk_test_key")
        assert is_valid is False
        assert "Couldn't reach Clerk" in (message or "")
        assert "connection reset by peer" not in (message or "")
