import json
import dataclasses
from datetime import UTC, date, datetime

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.greenhouse import (
    GreenhouseSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.greenhouse import (
    GREENHOUSE_ENDPOINTS,
    PAGE_SIZE,
    V3_ONLY_ENDPOINT_ERROR,
    GreenhouseResumeConfig,
    _build_auth,
    _build_initial_params,
    _format_datetime,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.settings import (
    ENDPOINTS,
    GREENHOUSE_V1,
    GREENHOUSE_V3,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.source import GreenhouseSource


def _driver() -> SourceDriver:
    return SourceDriver(
        GreenhouseSource(), GreenhouseSourceConfig(api_key="key", client_id="cid", client_secret="csecret")
    )


def _page(rows: list[dict[str, int]], next_url: str | None = None) -> ScriptedResponse:
    headers = {"Link": f'<{next_url}>; rel="next"'} if next_url else {}
    return ScriptedResponse(json=rows, headers=headers)


def _token() -> ScriptedResponse:
    return ScriptedResponse(json={"access_token": "test_token", "expires_in": 3600})


class TestFormatDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45.123Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),  # naive -> treated as UTC
            (date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("already-a-string", "already-a-string"),
        ],
    )
    def test_format_datetime(self, value: object, expected: str) -> None:
        assert _format_datetime(value) == expected


WATERMARK = datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)


class TestBuildInitialParams:
    @pytest.mark.parametrize(
        "endpoint, api_version, incremental_field, expected_filter",
        [
            # v1 filters through a separate `*_after` param; v3 filters on the field itself with a
            # pipe-delimited operator. Sending one version's syntax to the other silently drops the
            # filter (full re-sync every run) or 422s.
            ("candidates", GREENHOUSE_V1, "updated_at", {"updated_after": "2026-03-04T02:58:14.000Z"}),
            ("candidates", GREENHOUSE_V3, "updated_at", {"updated_at": "gte|2026-03-04T02:58:14.000Z"}),
            ("candidates", GREENHOUSE_V1, "created_at", {"created_after": "2026-03-04T02:58:14.000Z"}),
            ("candidates", GREENHOUSE_V3, "created_at", {"created_at": "gte|2026-03-04T02:58:14.000Z"}),
            ("applications", GREENHOUSE_V1, "last_activity_at", {"last_activity_after": "2026-03-04T02:58:14.000Z"}),
            ("applications", GREENHOUSE_V3, "last_activity_at", {"last_activity_at": "gte|2026-03-04T02:58:14.000Z"}),
            ("candidates", GREENHOUSE_V1, "somethingElse", {}),
            ("candidates", GREENHOUSE_V3, "somethingElse", {}),
        ],
    )
    def test_incremental_filter_syntax_per_version(
        self, endpoint: str, api_version: str, incremental_field: str, expected_filter: dict[str, str]
    ) -> None:
        params = _build_initial_params(GREENHOUSE_ENDPOINTS[endpoint], api_version, True, WATERMARK, incremental_field)
        assert params == {"per_page": PAGE_SIZE, **expected_filter}


class TestBuildAuth:
    @pytest.mark.parametrize(
        "api_version, api_key, client_id, client_secret",
        [
            (GREENHOUSE_V3, "test_key", None, None),
            (GREENHOUSE_V3, "test_key", "cid", None),
            (GREENHOUSE_V1, None, "cid", "csecret"),
        ],
    )
    def test_credentials_for_the_other_version_are_rejected(
        self, api_version: str, api_key: str | None, client_id: str | None, client_secret: str | None
    ) -> None:
        with pytest.raises(ValueError):
            _build_auth(api_version, api_key, client_id, client_secret)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, accept_forbidden, expected_valid",
        [
            (200, True, True),
        ],
    )
    def test_status_code_mapping(self, status_code: int, accept_forbidden: bool, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            is_valid, error = validate_credentials(GREENHOUSE_V1, api_key="test_key", accept_forbidden=accept_forbidden)

        assert is_valid is expected_valid
        assert (error is None) is expected_valid
        assert {request.path for request in network.requests_log} == {"/v1/candidates"}

    def test_per_schema_forbidden_surfaces_scope_error(self) -> None:
        with scripted_network([ScriptedResponse(status=403)]):
            is_valid, error = validate_credentials(
                GREENHOUSE_V1, api_key="test_key", path="/candidates", accept_forbidden=False
            )
        assert is_valid is False
        assert error is not None and "permission" in error

    @pytest.mark.parametrize(
        "api_version, expected_url",
        [
            (GREENHOUSE_V1, "https://harvest.greenhouse.io/v1/candidates?per_page=1"),
            (GREENHOUSE_V3, "https://harvest.greenhouse.io/v3/candidates?per_page=1"),
        ],
    )
    def test_probes_the_pinned_version(self, api_version: str, expected_url: str) -> None:
        # A v1-pinned source probed on the v3 path (or vice versa) reports a working key as broken.
        script = [_token(), ScriptedResponse(status=200)] if api_version == GREENHOUSE_V3 else [ScriptedResponse()]
        with scripted_network(script) as network:
            is_valid, error = validate_credentials(
                api_version, api_key="test_key", client_id="cid", client_secret="csecret"
            )

        assert is_valid is True
        assert error is None
        assert network.requests_log[-1].url == expected_url

    def test_v3_without_client_credentials_explains_what_to_create(self) -> None:
        is_valid, error = validate_credentials(GREENHOUSE_V3, api_key="test_key")
        assert is_valid is False
        assert error is not None and "OAuth" in error


class TestGreenhouseSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_partition_key_is_never_updated_at(self, endpoint: str) -> None:
        assert GREENHOUSE_ENDPOINTS[endpoint].partition_key not in ("updated_at", "last_activity_at")

    @pytest.mark.parametrize("endpoint", [name for name, config in GREENHOUSE_ENDPOINTS.items() if config.v3_only])
    def test_v3_only_endpoint_refuses_to_sync_on_v1(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [], api_version=GREENHOUSE_V1)

        assert isinstance(result.raised, ValueError)
        assert str(result.raised) == V3_ONLY_ENDPOINT_ERROR


class TestGreenhousePaginationAndResume:
    """Drive Greenhouse extraction through its real HTTP transport."""

    def test_fresh_run_follows_link_header(self) -> None:
        next_url = "https://harvest.greenhouse.io/v1/candidates?per_page=500&page=2"
        result = _driver().run(
            "candidates",
            [
                _page([{"id": 1}], next_url=next_url),
                _page([{"id": 2}]),  # no Link header -> last page
            ],
            api_version=GREENHOUSE_V1,
        )

        # The second request follows the Link URL with no extra params.
        assert result.raised is None
        assert result.urls == ["https://harvest.greenhouse.io/v1/candidates?per_page=500", next_url]
        assert result.params("per_page") == [str(PAGE_SIZE), str(PAGE_SIZE)]
        assert result.rows == [{"id": 1}, {"id": 2}]
        assert result.saved_states == [GreenhouseResumeConfig(next_url=next_url)]

    @pytest.mark.parametrize(
        "hostile_next_url",
        [
            "https://evil.example.com/v1/candidates?page=2",
            # An allowed hostname over a downgraded scheme still puts the credential on the wire.
            "http://harvest.greenhouse.io/v1/candidates?page=2",
        ],
    )
    def test_off_origin_next_link_is_rejected_before_a_request_is_sent(self, hostile_next_url: str) -> None:
        # The Link URL is followed verbatim, so a spoofed one would otherwise replay the
        # Authorization header (v3: a freshly minted Bearer token) to another origin.
        result = _driver().run("candidates", [_page([{"id": 1}], next_url=hostile_next_url)], api_version=GREENHOUSE_V1)

        assert isinstance(result.raised, ValueError)
        assert result.paths == ["/v1/candidates"]

    def test_cross_origin_redirect_is_not_followed(self) -> None:
        result = _driver().run(
            "candidates",
            [ScriptedResponse(status=302, headers={"Location": "https://evil.example.com/v1/candidates"})],
            api_version=GREENHOUSE_V1,
        )

        assert isinstance(result.raised, ValueError)
        assert result.paths == ["/v1/candidates"]

    def test_incremental_filter_applied_to_first_request(self) -> None:
        watermark = datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)
        result = _driver().run(
            "candidates",
            [_page([{"id": 1}])],
            api_version=GREENHOUSE_V1,
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
            incremental_field="updated_at",
        )

        assert result.raised is None
        assert result.requests[0].param("per_page") == str(PAGE_SIZE)
        assert result.requests[0].param("updated_after") == "2026-03-04T02:58:14.000Z"

    def test_resume_seeds_first_request_with_saved_next_url(self) -> None:
        saved_url = "https://harvest.greenhouse.io/v1/candidates?per_page=500&page=5"
        result = _driver().run(
            "candidates",
            [_page([{"id": 9}])],
            resume_state=GreenhouseResumeConfig(next_url=saved_url),
            api_version=GREENHOUSE_V1,
        )

        assert result.raised is None
        assert result.urls == [saved_url]
        assert result.rows == [{"id": 9}]


class TestResumeConfigSerialization:
    def test_round_trip(self) -> None:
        cfg = GreenhouseResumeConfig(next_url="https://harvest.greenhouse.io/v1/candidates?page=3")
        reconstituted = GreenhouseResumeConfig(**json.loads(json.dumps(dataclasses.asdict(cfg))))
        assert reconstituted == cfg
