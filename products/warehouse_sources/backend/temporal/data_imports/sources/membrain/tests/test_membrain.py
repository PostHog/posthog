import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.membrain import (
    MembrainSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.membrain.membrain import (
    MembrainPaginator,
    MembrainResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.membrain.source import MembrainSource


def _driver() -> SourceDriver:
    return SourceDriver(MembrainSource(), MembrainSourceConfig(api_key="mb-key", subdomain="acme"))


def _envelope(items: list[dict[str, Any]], count: int, start: int) -> dict[str, Any]:
    # Membrain serializes every value as a JSON string, including the paging counters.
    return {
        "count": str(count),
        "from": str(start),
        "to": str(start + len(items)),
        "items": items,
    }


def _response(body: Any) -> Response:
    resp = Response()
    resp._content = json.dumps(body).encode()
    return resp


class TestMembrainPaginator:
    def _update(self, paginator: MembrainPaginator, body: Any) -> None:
        paginator.update_state(_response(body))

    def test_terminates_when_to_reaches_count(self) -> None:
        paginator = MembrainPaginator()
        self._update(paginator, _envelope([{"Id": "a"}], count=1, start=0))

        assert paginator.has_next_page is False
        assert paginator.get_resume_state() is None

    @parameterized.expand(
        [
            ("missing_counters", {"items": [{"Id": "a"}]}),
            ("non_dict_body", [{"Id": "a"}]),
        ]
    )
    def test_fails_loudly_on_unexpected_envelope(self, _name: str, body: Any) -> None:
        # Missing count/to must not be treated as a graceful last page: that could truncate a
        # full-refresh sync without ever raising.
        paginator = MembrainPaginator()
        with pytest.raises(ValueError):
            self._update(paginator, body)

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
    def test_follows_from_offsets_until_count_reached(self) -> None:
        result = _driver().run(
            "companies",
            [
                ScriptedResponse(json=_envelope([{"Id": "a"}, {"Id": "b"}], count=3, start=0)),
                ScriptedResponse(json=_envelope([{"Id": "c"}], count=3, start=2)),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"Id": "a"}, {"Id": "b"}, {"Id": "c"}]
        # A fresh run sends no From; the second page starts at the first page's `to`.
        assert result.params("From") == [None, "2"]
        assert result.saved_states == [MembrainResumeConfig(next_from=2)]

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "companies",
            [ScriptedResponse(json=_envelope([{"Id": "c"}], count=3, start=2))],
            resume_state=MembrainResumeConfig(next_from=2),
        )

        assert result.raised is None
        assert result.rows == [{"Id": "c"}]
        # Offset 0 must never be refetched on resume.
        assert result.params("From") == ["2"]

    def test_key_rides_the_apikey_header_and_never_the_url(self) -> None:
        result = _driver().run("companies", [ScriptedResponse(json=_envelope([], count=0, start=0))])

        assert result.raised is None
        assert result.requests[0].headers["apikey"] == "mb-key"
        assert result.requests[0].param("APIKey") is None
        assert "mb-key" not in result.urls[0]

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
    def test_documented_params_sent_per_endpoint(self, endpoint: str, expected: dict[str, str]) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=_envelope([], count=0, start=0))])

        assert result.raised is None
        assert {key: values[0] for key, values in result.queries[0].items()} == expected

    @parameterized.expand([("prospects",), ("opportunities",), ("account_growth_items",), ("tickets",)])
    def test_unsorted_endpoints_never_save_or_load_resume_state(self, endpoint: str) -> None:
        # No documented SortBy means no established stable order, so an offset resume across runs
        # could silently skip or duplicate rows if that order shifts between them.
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json=_envelope([{"Id": "a"}, {"Id": "b"}], count=3, start=0)),
                ScriptedResponse(json=_envelope([{"Id": "c"}], count=3, start=2)),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"Id": "a"}, {"Id": "b"}, {"Id": "c"}]
        assert result.params("From") == [None, "2"]
        assert result.saved_states == []


class TestBareArrayEndpoints:
    @parameterized.expand(
        [
            ("users", "/users/"),
            ("roles", "/roles/"),
            ("products", "/products/"),
            ("currencies", "/currencies/"),
            ("activity_types", "/activityTypes/"),
            ("ticket_processes", "/ticketProcesses/"),
            ("account_growth_processes", "/accountGrowthProcesses/"),
        ]
    )
    def test_yields_rows_from_a_single_unpaged_request(self, endpoint: str, path: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[{"Id": "u1"}, {"Id": "u2"}])])

        assert result.raised is None
        assert result.rows == [{"Id": "u1"}, {"Id": "u2"}]
        assert len(result.requests) == 1
        assert result.requests[0].path == f"/API/v2{path}"
        assert result.params("From") == [None]
        assert result.saved_states == []

    def test_error_object_on_200_fails_loudly(self) -> None:
        # Membrain reports some failures as HTTP 200 with an error body; syncing it as a row
        # would silently produce a one-row garbage table.
        result = _driver().run("users", [ScriptedResponse(json={"error": "Instance not found"})])

        assert isinstance(result.raised, ValueError)
        assert "list response body" in str(result.raised)


class TestMalformedPagedPayload:
    @parameterized.expand(
        [
            ("error_object", {"error": "Instance not found"}),
            ("missing_items", {"count": "0", "from": "0", "to": "0"}),
        ]
    )
    def test_body_without_items_fails_loudly(self, _name: str, body: Any) -> None:
        result = _driver().run("companies", [ScriptedResponse(json=body)])

        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestErrorHandling:
    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_http_error(self, _name: str, status: int) -> None:
        result = _driver().run("companies", [ScriptedResponse(status=status, json={})])

        # get_non_retryable_errors matches on this stable prefix.
        assert isinstance(result.raised, HTTPError)
        assert str(result.raised).startswith(f"{status} Client Error")

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_transient_statuses_are_retried_then_recover(self, _name: str, status: int) -> None:
        result = _driver().run(
            "companies",
            [
                ScriptedResponse(status=status, json={}),
                ScriptedResponse(json=_envelope([{"Id": "a"}], count=1, start=0)),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"Id": "a"}]
        assert len(result.requests) == 2


class TestCustomFields:
    def test_flattens_per_entity_arrays_into_rows_with_entity_type(self) -> None:
        body = {
            "companyCustomFields": [{"Id": "cf-1", "Name": "Tier", "Type": "Text"}],
            "contactCustomFields": [
                {"Id": "cf-2", "Name": "Birthday", "Type": "Date"},
                {"Id": "cf-3", "Name": "Segment", "Type": "SingleSelect", "Options": [{"Id": "o1", "Name": "A"}]},
            ],
        }
        result = _driver().run("custom_fields", [ScriptedResponse(json=body)])

        assert result.raised is None
        assert result.rows == [
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
        result = _driver().run("custom_fields", [ScriptedResponse(json=body)])

        assert isinstance(result.raised, ValueError)
        assert "customFields" in str(result.raised)


class TestValidateCredentials:
    def test_a_bare_user_list_is_valid(self) -> None:
        with scripted_network([ScriptedResponse(json=[{"Id": "u1", "Name": "Ada"}])]) as network:
            assert validate_credentials("mb-key", "acme") == (True, None)
        assert network.requests_log[0].path == "/API/v2/users/"
        assert network.requests_log[0].headers["apikey"] == "mb-key"

    @parameterized.expand(
        [
            ("instance_not_found", {"error": "Instance not found"}, "subdomain"),
            ("other_error", {"error": "Invalid key"}, "API key"),
        ]
    )
    def test_200_error_bodies_map_to_guidance(self, _name: str, body: Any, expected_fragment: str) -> None:
        # Membrain reports these failures as HTTP 200 with an error body, so the status alone
        # would wrongly validate the credentials.
        with scripted_network([ScriptedResponse(json=body)]):
            is_valid, message = validate_credentials("mb-key", "acme")

        assert is_valid is False
        assert message is not None and expected_fragment in message

    def test_non_json_200_is_rejected(self) -> None:
        with scripted_network([ScriptedResponse(body=b"<html>maintenance</html>")]):
            is_valid, message = validate_credentials("mb-key", "acme")

        assert is_valid is False
        assert message is not None and "unexpected response" in message

    def test_connection_error_maps_to_fixed_message(self) -> None:
        # The probe swallows the exception and returns a fixed message, so raw exception text
        # never reaches the user.
        with scripted_network(always(ConnectionResetError("boom"))):
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
        body: Any = {"companyCustomFields": []} if endpoint == "custom_fields" else []
        if endpoint == "companies":
            body = _envelope([], count=0, start=0)
        result = _driver().run(endpoint, [ScriptedResponse(json=body)])

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.primary_keys == primary_keys
        assert response.partition_mode == partition_mode
        if partition_mode == "datetime":
            assert response.partition_keys == ["CreatedDate"]
