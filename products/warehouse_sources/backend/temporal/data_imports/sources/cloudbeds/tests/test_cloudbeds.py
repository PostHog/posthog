from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudbeds.cloudbeds import (
    CLOUDBEDS_API_VERSION_V1_2,
    CLOUDBEDS_API_VERSION_V1_3,
    PAGE_SIZE,
    CloudbedsResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudbeds.settings import (
    CLOUDBEDS_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudbeds.source import CloudbedsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudbeds import (
    CloudbedsSourceConfig,
)


def _driver(property_id: str | None = None) -> SourceDriver:
    return SourceDriver(CloudbedsSource(), CloudbedsSourceConfig(api_key="cbat_key", property_id=property_id))


def _response(rows: list[dict[str, Any]] | None = None, *, body: dict[str, Any] | None = None) -> ScriptedResponse:
    items = rows or []
    return ScriptedResponse(
        json=body if body is not None else {"success": True, "data": items, "count": len(items), "total": len(items)}
    )


class TestPagination:
    def _full_page(self, start: int) -> list[dict[str, Any]]:
        return [{"reservationID": str(start + i)} for i in range(PAGE_SIZE)]

    def test_paginates_by_page_number_and_checkpoints_after_full_page(self) -> None:
        result = _driver().run("reservations", [_response(self._full_page(0)), _response([{"reservationID": "999"}])])

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 1
        assert result.params("pageNumber") == ["1", "2"]
        assert result.params("pageSize") == [str(PAGE_SIZE), str(PAGE_SIZE)]
        # Checkpoint saved after the first full page (points at page 2); the short page then ends it.
        assert result.saved_states == [CloudbedsResumeConfig(page=2)]
        assert result.committed_states == [CloudbedsResumeConfig(page=2)]

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "reservations", [_response([{"reservationID": "5"}])], resume_state=CloudbedsResumeConfig(page=3)
        )

        assert result.raised is None
        assert result.rows == [{"reservationID": "5"}]
        # Page 1 and 2 must never be fetched on resume.
        assert result.params("pageNumber") == ["3"]

    def test_rooms_are_flattened_with_property_id(self) -> None:
        result = _driver().run(
            "rooms",
            [
                _response(
                    [
                        {
                            "propertyID": "1",
                            "propertyName": "Hotel One",
                            "rooms": [{"roomID": "r1", "roomName": "101"}, {"roomID": "r2", "roomName": "102"}],
                        },
                        {"propertyID": "2", "propertyName": "Hotel Two", "rooms": []},
                    ]
                )
            ],
        )

        assert result.raised is None
        # Each nested room becomes its own row with the parent propertyID copied in; the parent with
        # an empty `rooms` list contributes nothing.
        assert result.rows == [
            {"roomID": "r1", "roomName": "101", "propertyID": "1"},
            {"roomID": "r2", "roomName": "102", "propertyID": "1"},
        ]

    def test_users_are_exploded_out_of_the_per_property_map(self) -> None:
        # getUsers keys `data` by property ID instead of returning a list, so each property's users
        # arrive nested under the ID they belong to.
        result = _driver().run(
            "users",
            [
                _response(
                    None,
                    body={
                        "success": True,
                        "data": {
                            "1": [{"userID": "u1", "email": "a@example.com"}, {"userID": "u2"}],
                            "2": [{"userID": "u1", "email": "a@example.com"}],
                        },
                    },
                )
            ],
        )

        assert result.raised is None
        # The same user at two properties must stay two rows, each carrying its own propertyID -
        # that is what makes the ["propertyID", "userID"] key unique.
        assert result.rows == [
            {"userID": "u1", "email": "a@example.com", "propertyID": "1"},
            {"userID": "u2", "propertyID": "1"},
            {"userID": "u1", "email": "a@example.com", "propertyID": "2"},
        ]

    @parameterized.expand([("rate_plans", "propertyIDs"), ("users", "property_ids")])
    def test_property_is_scoped_under_the_param_the_endpoint_accepts(self, endpoint: str, param: str) -> None:
        result = _driver(property_id="12345").run(endpoint, [_response(body={"success": True, "data": {}})])

        assert result.raised is None
        # These two methods spell the property filter their own way; sending `propertyID` instead
        # would leave a group credential reading every property it can see.
        assert result.requests[0].param(param) == "12345"
        assert result.requests[0].param("propertyID") is None


class TestApiVersion:
    @parameterized.expand([(CLOUDBEDS_API_VERSION_V1_2,), (CLOUDBEDS_API_VERSION_V1_3,)])
    def test_requested_version_is_the_url_segment(self, api_version: str) -> None:
        result = _driver().run("reservations", [_response([{"reservationID": "1"}])], api_version=api_version)

        assert result.raised is None
        # The resolved pin must reach the request path verbatim so a v1.2-pinned source never drifts
        # onto v1.3 (the default) or vice versa.
        assert result.paths == [f"/api/{api_version}/getReservations"]


class TestFailLoud:
    @parameterized.expand(
        [("missing_data_key", {"success": True}), ("success_false", {"success": False, "message": "Access denied"})]
    )
    def test_missing_data_fails_loud(self, _name: str, body: dict[str, Any]) -> None:
        result = _driver().run("reservations", [_response(body=body)])

        # A 200 body without `data` (a `success: false` envelope or a changed shape) must fail loud,
        # not silently sync 0 rows.
        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)
        assert result.rows == []

    @parameterized.expand(
        [
            ("unauthorized", 401, "Unauthorized"),
            ("forbidden", 403, "Forbidden"),
        ]
    )
    def test_auth_failure_raises_matchable_error(self, _name: str, status: int, reason: str) -> None:
        result = _driver().run("reservations", [ScriptedResponse(status=status, json={"success": False})])

        assert isinstance(result.raised, Exception)
        message = str(result.raised)
        # The stable "<status> Client Error: <reason> for url: https://api.cloudbeds.com" prefix is
        # what get_non_retryable_errors matches on to surface an actionable message.
        assert message.startswith(f"{status} Client Error: {reason} for url: https://api.cloudbeds.com")
        assert any(key in message for key in CloudbedsSource().get_non_retryable_errors())

    def test_api_key_is_never_leaked_into_error(self) -> None:
        # The tracked session redacts the credential from raised errors.
        result = _driver().run("reservations", [ScriptedResponse(status=401)])

        assert isinstance(result.raised, Exception)
        assert "cbat_key" not in str(result.raised)
        assert result.requests[0].headers["authorization"] == "Bearer cbat_key"
        assert "cbat_key" in result.session_options[0]["redact_values"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
        ]
    )
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert validate_credentials("cbat_key", CLOUDBEDS_API_VERSION_V1_3) == (expected_valid, expected_message)
        assert network.requests_log[0].path == "/api/v1.3/getHotels"

    def test_probe_scopes_to_property_when_configured(self) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            validate_credentials("cbat_key", CLOUDBEDS_API_VERSION_V1_3, property_id="12345")
        assert network.requests_log[0].param("propertyID") == "12345"

    @parameterized.expand([(CLOUDBEDS_API_VERSION_V1_2,), (CLOUDBEDS_API_VERSION_V1_3,)])
    def test_probe_url_carries_requested_version(self, api_version: str) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            validate_credentials("cbat_key", api_version)
        assert network.requests_log[0].url.startswith(f"https://api.cloudbeds.com/api/{api_version}/getHotels")


class TestCloudbedsSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        body: dict[str, Any] = {"success": True, "data": {} if endpoint == "users" else []}
        result = _driver().run(endpoint, [_response(body=body)])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == CLOUDBEDS_ENDPOINTS[endpoint].primary_keys
        # No creation timestamp is verified stable across every object, so we don't partition.
        assert result.response.partition_mode is None

    def test_endpoint_catalog_is_consistent(self) -> None:
        assert set(CLOUDBEDS_ENDPOINTS) == set(ENDPOINTS)
        assert all(config.primary_keys for config in CLOUDBEDS_ENDPOINTS.values())
