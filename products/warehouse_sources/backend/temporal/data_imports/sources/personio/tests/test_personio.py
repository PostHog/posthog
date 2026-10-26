from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.personio import (
    PersonioSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.personio.personio import (
    PersonioResumeConfig,
    _format_updated_at,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.personio.settings import (
    ENDPOINTS,
    PERSONIO_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.personio.source import PersonioSource


def _page(items: list[dict[str, Any]], next_url: str | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"_data": items, "_meta": {"links": {}}}
    if next_url:
        body["_meta"]["links"]["next"] = {"href": next_url}
    return ScriptedResponse(json=body)


def _token_response(status_code: int = 200, expires_in: int = 86400) -> ScriptedResponse:
    body: dict[str, Any] = (
        {"access_token": "the-token", "expires_in": expires_in, "token_type": "Bearer"}
        if status_code < 300
        else {"error": "invalid_client"}
    )
    return ScriptedResponse(status=status_code, json=body)


def _driver() -> SourceDriver:
    return SourceDriver(PersonioSource(), PersonioSourceConfig(client_id="cid", client_secret="sec"))


class TestFormatUpdatedAt:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00Z"),
            ("2024-01-02T03:04:05Z", "2024-01-02T03:04:05Z"),
        ],
    )
    def test_format_values(self, value: Any, expected: str) -> None:
        assert _format_updated_at(value) == expected


class TestValidateCredentials:
    def test_valid_when_token_mints(self) -> None:
        with scripted_network([_token_response()]) as network:
            assert validate_credentials("cid", "sec") is True

        assert network.requests_log[0].path == "/v2/auth/token"

    def test_mint_sends_client_credentials_in_body(self) -> None:
        with scripted_network([_token_response()]) as network:
            validate_credentials("cid", "sec")

        request = network.requests_log[0]
        # Body-mode client auth: credentials ride in the form body, no HTTP Basic auth tuple.
        assert request.method == "POST"
        assert request.url == "https://api.personio.de/v2/auth/token"
        assert request.body is not None
        assert parse_qs(request.body.decode()) == {
            "grant_type": ["client_credentials"],
            "client_id": ["cid"],
            "client_secret": ["sec"],
        }
        assert "authorization" not in request.headers

    def test_invalid_when_token_mint_rejected(self) -> None:
        with scripted_network([_token_response(status_code=401)]):
            assert validate_credentials("cid", "sec") is False


class TestGetRows:
    def test_paginates_via_meta_next_link(self) -> None:
        next_url = "https://api.personio.de/v2/persons?cursor=cur_abc&limit=50"
        result = _driver().run(
            "persons",
            [_token_response(), _page([{"id": "1"}], next_url=next_url), _page([{"id": "2"}])],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2"]
        assert result.saved_states == [PersonioResumeConfig(next_url=next_url)]
        # The self-contained _meta.links.next.href link is followed verbatim on the second request.
        assert result.requests[-1].url == next_url

    def test_requests_carry_bearer_token(self) -> None:
        result = _driver().run("persons", [_token_response(), _page([])])

        assert result.raised is None
        assert result.requests[-1].headers["authorization"] == "Bearer the-token"

    def test_mints_token_once_across_pages(self) -> None:
        result = _driver().run(
            "persons",
            [
                _token_response(),
                _page([{"id": "1"}], next_url="https://api.personio.de/v2/persons?cursor=p2"),
                _page([{"id": "2"}]),
            ],
        )

        assert result.raised is None
        # One mint covers the whole run while the ~24h token is unexpired.
        assert result.paths.count("/v2/auth/token") == 1

    def test_remints_token_when_expired_mid_run(self) -> None:
        # expires_in=0 forces a re-mint per request — the deterministic stand-in for a sync
        # outliving the ~24h token lifetime. Replaces the pre-framework reactive-401 re-mint.
        result = _driver().run(
            "persons",
            [
                _token_response(expires_in=0),
                _page([{"id": "1"}], next_url="https://api.personio.de/v2/persons?cursor=p2"),
                _token_response(expires_in=0),
                _page([{"id": "2"}]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2"]
        assert result.paths.count("/v2/auth/token") == 2

    def test_incremental_persons_uses_strict_gt_filter(self) -> None:
        result = _driver().run(
            "persons",
            [_token_response(), _page([])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[-1].param("updated_at.gt") == "2024-01-02T00:00:00Z"
        assert result.requests[-1].param("limit") == "50"

    def test_incremental_absence_periods_uses_gte_filter(self) -> None:
        result = _driver().run(
            "absence_periods",
            [_token_response(), _page([])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[-1].param("updated_at.gte") == "2024-01-02T00:00:00Z"
        assert result.requests[-1].param("limit") == "100"

    def test_full_refresh_has_no_filter(self) -> None:
        result = _driver().run("persons", [_token_response(), _page([])])

        assert result.raised is None
        assert result.requests[-1].param("updated_at.gt") is None
        assert result.requests[-1].param("limit") == "50"

    @pytest.mark.parametrize(
        "endpoint, expected_limit",
        [
            ("salary_bands", "100"),
            ("cost_centers", "100"),
            ("recruiting_jobs", "200"),
            ("recruiting_categories", None),
        ],
    )
    def test_full_refresh_only_endpoint_never_sends_timestamp_filter(
        self, endpoint: str, expected_limit: str | None
    ) -> None:
        # These endpoints have no usable updated_at cursor, so incremental_param is None. Even if
        # incremental is requested, the request must go out as a full refresh with no timestamp
        # param — sending one the API ignores would silently claim a filtered sync.
        result = _driver().run(
            endpoint,
            [_token_response(), _page([])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
        )

        assert result.raised is None
        assert not any(key.startswith("updated_at") for key in result.requests[-1].query)
        assert result.requests[-1].param("limit") == expected_limit

    def test_resumes_from_saved_state(self) -> None:
        resume_url = "https://api.personio.de/v2/persons?cursor=cur_resume"
        result = _driver().run(
            "persons",
            [_token_response(), _page([{"id": "9"}])],
            resume_state=PersonioResumeConfig(next_url=resume_url),
        )

        assert result.raised is None
        assert result.requests[-1].url == resume_url

    def test_empty_page_stops_even_with_next_link(self) -> None:
        result = _driver().run(
            "persons",
            [_token_response(), _page([], next_url="https://api.personio.de/v2/persons?cursor=loop")],
        )

        assert result.raised is None
        assert result.rows == []
        assert result.paths == ["/v2/auth/token", "/v2/persons"]
        assert result.saved_states == []

    def test_rejects_off_host_next_url(self) -> None:
        # SSRF guard: a _meta.links.next.href pointing off api.personio.de is rejected before the
        # request (and its bearer token) leaves the process.
        result = _driver().run(
            "persons",
            [_token_response(), _page([{"id": "1"}], next_url="https://evil.example.com/v2/persons?cursor=x")],
        )

        assert isinstance(result.raised, ValueError)
        assert result.paths == ["/v2/auth/token", "/v2/persons"]

    def test_rejects_off_host_resume_url(self) -> None:
        result = _driver().run(
            "persons",
            [_token_response()],
            resume_state=PersonioResumeConfig(next_url="https://evil.example.com/v2/persons"),
        )

        assert isinstance(result.raised, ValueError)
        assert "/v2/persons" not in result.paths
        assert result.saved_states == []


class TestPersonioSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = PERSONIO_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [_token_response(), _page([])])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(PERSONIO_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config: Any) -> None:
        if config.partition_key:
            assert config.partition_key == "created_at"
