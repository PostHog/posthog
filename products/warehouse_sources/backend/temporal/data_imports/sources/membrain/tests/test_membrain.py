import json
from typing import Any, cast

import pytest
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.membrain.membrain import (
    MembrainPaginator,
    MembrainResumeConfig,
    membrain_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials and the custom-fields iterator build their own tracked session in the
# membrain module.
MEMBRAIN_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.membrain.membrain.make_tracked_session"
)

_REASONS = {401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 500: "Internal Server Error"}


def _envelope(items: list[dict[str, Any]], count: int, start: int) -> dict[str, Any]:
    # Membrain serializes every value as a JSON string, including the paging counters.
    return {
        "count": str(count),
        "from": str(start),
        "to": str(start + len(items)),
        "items": items,
    }


def _response(body: Any, *, status: int = 200, raw: bytes | None = None) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = raw if raw is not None else json.dumps(body).encode()
    resp.url = "https://acme.membrain.com/API/v2/companies/"
    resp.reason = cast("str", _REASONS.get(status))
    return resp


def _make_manager(resume_state: MembrainResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[Any]]:
    """Wire a mock session; return (param_snapshots, auth_snapshots) captured AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so a snapshot copy per
    prepared request is the only way to see each page's params.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    auth_snapshots: list[Any] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        auth_snapshots.append(request.auth)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, auth_snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager: Any, endpoint: str = "companies") -> Any:
    return membrain_source(
        api_key="mb-key",
        subdomain="acme",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


class TestMembrainPaginator:
    def _update(self, paginator: MembrainPaginator, body: Any) -> None:
        paginator.update_state(_response(body))

    def test_advances_to_the_envelope_to_offset(self) -> None:
        paginator = MembrainPaginator()
        self._update(paginator, _envelope([{"Id": "a"}], count=250, start=0))

        assert paginator.has_next_page is True
        assert paginator.get_resume_state() == {"next_from": 1}

    def test_terminates_when_to_reaches_count(self) -> None:
        paginator = MembrainPaginator()
        self._update(paginator, _envelope([{"Id": "a"}], count=1, start=0))

        assert paginator.has_next_page is False
        assert paginator.get_resume_state() is None

    def test_terminates_when_to_does_not_advance(self) -> None:
        # A `to` equal to the offset we requested would refetch the same window forever.
        paginator = MembrainPaginator()
        paginator.set_resume_state({"next_from": 100})
        self._update(paginator, {"count": "250", "from": "100", "to": "100", "items": []})

        assert paginator.has_next_page is False

    @parameterized.expand(
        [
            ("missing_counters", {"items": [{"Id": "a"}]}),
            ("non_dict_body", [{"Id": "a"}]),
        ]
    )
    def test_terminates_on_unexpected_envelope(self, _name: str, body: Any) -> None:
        paginator = MembrainPaginator()
        self._update(paginator, body)

        assert paginator.has_next_page is False

    def test_non_numeric_counter_fails_loudly(self) -> None:
        paginator = MembrainPaginator()
        with pytest.raises(ValueError):
            self._update(paginator, {"count": "many", "from": "0", "to": "1", "items": []})

    def test_set_resume_state_round_trip(self) -> None:
        paginator = MembrainPaginator()
        paginator.set_resume_state({"next_from": "200"})

        request = mock.MagicMock(params=None)
        paginator.init_request(request)

        assert request.params == {"From": 200}
        assert paginator.has_next_page is True


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_from_offsets_until_count_reached(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(
            session,
            [
                _response(_envelope([{"Id": "a"}, {"Id": "b"}], count=3, start=0)),
                _response(_envelope([{"Id": "c"}], count=3, start=2)),
            ],
        )

        rows = _rows(_source(_make_manager()))

        assert rows == [{"Id": "a"}, {"Id": "b"}, {"Id": "c"}]
        # A fresh run sends no From; the second page starts at the first page's `to`.
        assert [p.get("From") for p in params] == [None, 2]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_next_from_after_yielding_each_non_terminal_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(_envelope([{"Id": "a"}, {"Id": "b"}], count=3, start=0)),
                _response(_envelope([{"Id": "c"}], count=3, start=2)),
            ],
        )

        manager = _make_manager()
        _rows(_source(manager))

        assert [c.args[0].next_from for c in manager.save_state.call_args_list] == [2]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response(_envelope([{"Id": "c"}], count=3, start=2))])

        manager = _make_manager(MembrainResumeConfig(next_from=2))
        rows = _rows(_source(manager))

        assert rows == [{"Id": "c"}]
        # Offset 0 must never be refetched on resume.
        assert params[0]["From"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_key_rides_the_apikey_header_and_never_the_url(self, MockSession) -> None:
        session = MockSession.return_value
        params, auths = _wire(session, [_response(_envelope([], count=0, start=0))])

        _rows(_source(_make_manager()))

        assert "APIKey" not in params[0]
        auth = auths[0]
        assert isinstance(auth, APIKeyAuth)
        assert (auth.name, auth.location) == ("APIKey", "header")

    @parameterized.expand(
        [
            ("companies", {"IncludeDeleted": "true", "SortBy": "CreatedDate ASC"}),
            ("contacts", {"IncludeDeleted": "true", "IncludeRetired": "true", "SortBy": "CreatedDate ASC"}),
            ("activities", {"SortBy": "CreatedDate ASC"}),
            # These endpoints document neither SortBy nor Include* params, so none are sent.
            ("prospects", {}),
            ("opportunities", {}),
            ("account_growth_items", {}),
            ("tickets", {}),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_documented_params_sent_per_endpoint(self, endpoint: str, expected: dict[str, str], MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response(_envelope([], count=0, start=0))])

        _rows(_source(_make_manager(), endpoint=endpoint))

        assert params[0] == expected


class TestBareArrayEndpoints:
    @parameterized.expand([("users",), ("roles",), ("products",)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_yields_rows_from_a_single_unpaged_request(self, endpoint: str, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response([{"Id": "u1"}, {"Id": "u2"}])])

        manager = _make_manager()
        rows = _rows(_source(manager, endpoint=endpoint))

        assert rows == [{"Id": "u1"}, {"Id": "u2"}]
        assert session.send.call_count == 1
        assert "From" not in params[0]
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_error_object_on_200_fails_loudly(self, MockSession) -> None:
        # Membrain reports some failures as HTTP 200 with an error body; syncing it as a row
        # would silently produce a one-row garbage table.
        session = MockSession.return_value
        _wire(session, [_response({"error": "Instance not found"})])

        with pytest.raises(ValueError, match="list response body"):
            _rows(_source(_make_manager(), endpoint="users"))


class TestMalformedPagedPayload:
    @parameterized.expand(
        [
            ("error_object", {"error": "Instance not found"}),
            ("missing_items", {"count": "0", "from": "0", "to": "0"}),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_body_without_items_fails_loudly(self, _name: str, body: Any, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(body)])

        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source(_make_manager()))


class TestErrorHandling:
    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_http_error(self, _name: str, status: int, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({}, status=status)])

        with pytest.raises(HTTPError) as exc_info:
            _rows(_source(_make_manager()))

        # get_non_retryable_errors matches on this stable prefix.
        assert str(exc_info.value).startswith(f"{status} Client Error")

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch("time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_transient_statuses_are_retried_then_recover(self, _name: str, status: int, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({}, status=status),
                _response(_envelope([{"Id": "a"}], count=1, start=0)),
            ],
        )

        rows = _rows(_source(_make_manager()))

        assert rows == [{"Id": "a"}]
        assert session.send.call_count == 2


class TestCustomFields:
    def _probe(self, response_or_exc: Any) -> Any:
        session = mock.MagicMock()
        if isinstance(response_or_exc, Exception):
            session.get.side_effect = response_or_exc
        else:
            session.get.return_value = response_or_exc
        return mock.patch(MEMBRAIN_SESSION_PATCH, return_value=session)

    def test_flattens_per_entity_arrays_into_rows_with_entity_type(self) -> None:
        body = {
            "companyCustomFields": [{"Id": "cf-1", "Name": "Tier", "Type": "Text"}],
            "contactCustomFields": [
                {"Id": "cf-2", "Name": "Birthday", "Type": "Date"},
                {"Id": "cf-3", "Name": "Segment", "Type": "SingleSelect", "Options": [{"Id": "o1", "Name": "A"}]},
            ],
        }
        with self._probe(_response(body)):
            rows = _rows(_source(_make_manager(), endpoint="custom_fields"))

        assert rows == [
            {"Id": "cf-1", "Name": "Tier", "Type": "Text", "EntityType": "company"},
            {"Id": "cf-2", "Name": "Birthday", "Type": "Date", "EntityType": "contact"},
            {
                "Id": "cf-3",
                "Name": "Segment",
                "Type": "SingleSelect",
                "Options": [{"Id": "o1", "Name": "A"}],
                "EntityType": "contact",
            },
        ]

    @parameterized.expand(
        [
            ("error_object", {"error": "Instance not found"}),
            ("bare_array", [{"Id": "cf-1"}]),
        ]
    )
    def test_unexpected_shape_fails_loudly(self, _name: str, body: Any) -> None:
        with self._probe(_response(body)):
            with pytest.raises(ValueError, match="customFields"):
                _rows(_source(_make_manager(), endpoint="custom_fields"))


class TestValidateCredentials:
    def _probe(self, response_or_exc: Any) -> Any:
        session = mock.MagicMock()
        if isinstance(response_or_exc, Exception):
            session.get.side_effect = response_or_exc
        else:
            session.get.return_value = response_or_exc
        return mock.patch(MEMBRAIN_SESSION_PATCH, return_value=session)

    def test_a_bare_user_list_is_valid(self) -> None:
        with self._probe(_response([{"Id": "u1", "Name": "Ada"}])):
            assert validate_credentials("mb-key", "acme") == (True, None)

    @parameterized.expand(
        [
            ("instance_not_found", {"error": "Instance not found"}, "subdomain"),
            ("other_error", {"error": "Invalid key"}, "API key"),
        ]
    )
    def test_200_error_bodies_map_to_guidance(self, _name: str, body: Any, expected_fragment: str) -> None:
        # Membrain reports these failures as HTTP 200 with an error body, so the status alone
        # would wrongly validate the credentials.
        with self._probe(_response(body)):
            is_valid, message = validate_credentials("mb-key", "acme")

        assert is_valid is False
        assert message is not None and expected_fragment in message

    @parameterized.expand(
        [
            ("unauthorized", 401, "Invalid Membrain API key"),
            ("forbidden", 403, "Invalid Membrain API key"),
            ("server_error", 500, "Membrain returned HTTP 500"),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_prefix: str) -> None:
        with self._probe(_response({}, status=status)):
            is_valid, message = validate_credentials("mb-key", "acme")

        assert is_valid is False
        assert message is not None and message.startswith(expected_prefix)

    def test_non_json_200_is_rejected(self) -> None:
        with self._probe(_response(None, raw=b"<html>maintenance</html>")):
            is_valid, message = validate_credentials("mb-key", "acme")

        assert is_valid is False
        assert message is not None and "unexpected response" in message

    def test_connection_error_maps_to_fixed_message(self) -> None:
        # The probe swallows the exception and returns a fixed message, so raw exception text
        # never reaches the user.
        with self._probe(RuntimeError("boom")):
            is_valid, message = validate_credentials("mb-key", "acme")

        assert is_valid is False
        assert message is not None and message.startswith("Could not connect to Membrain")


class TestMembrainSourceResponse:
    @parameterized.expand(
        [
            ("companies", ["Id"], "datetime"),
            ("users", ["Id"], None),
            ("custom_fields", ["EntityType", "Id"], None),
        ]
    )
    def test_primary_keys_and_partitioning_follow_endpoint_shape(
        self, endpoint: str, primary_keys: list[str], partition_mode: str | None
    ) -> None:
        response = _source(_make_manager(), endpoint=endpoint)

        assert response.primary_keys == primary_keys
        assert response.partition_mode == partition_mode
        if partition_mode == "datetime":
            assert response.partition_keys == ["CreatedDate"]
