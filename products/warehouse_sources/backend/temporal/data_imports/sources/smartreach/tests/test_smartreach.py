from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.smartreach import (
    SmartreachSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.settings import (
    ENDPOINTS,
    SMARTREACH_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.smartreach import (
    SMARTREACH_API_V1,
    SMARTREACH_API_V3,
    SMARTREACH_BASE_URL,
    SMARTREACH_BASE_URLS,
    SmartreachResumeConfig,
    check_access,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.source import SmartreachSource


def _response(
    rows: list[dict[str, Any]] | None, data_key: str, next_url: str | None, status: int = 200
) -> ScriptedResponse:
    # v1 envelope: the row list is nested under `data.<data_key>`.
    body: dict[str, Any] = {"data": {data_key: rows if rows is not None else []}, "links": {"next": next_url}}
    return ScriptedResponse(status=status, json=body)


def _response_v3(rows: list[dict[str, Any]] | None, data_key: str, next_url: str | None) -> ScriptedResponse:
    # v3 envelope: the row list sits at the response root (e.g. `prospects`), not under `data`.
    return ScriptedResponse(json={data_key: rows if rows is not None else [], "links": {"next": next_url}})


def _run(
    script: Script,
    endpoint: str = "prospects",
    api_version: str = SMARTREACH_API_V1,
    smartreach_team_id: str | None = None,
    **inputs: Any,
) -> DriveResult:
    config = SmartreachSourceConfig(api_key="uk_test", team_id=smartreach_team_id)
    return SourceDriver(SmartreachSource(), config).run(endpoint, script, api_version=api_version, **inputs)


class TestPagination:
    def test_resumes_from_saved_cursor_url(self) -> None:
        p2 = f"{SMARTREACH_BASE_URL}/prospects?cursor=abc"
        p3 = f"{SMARTREACH_BASE_URL}/prospects?cursor=def"

        result = _run(
            [
                _response([{"id": 2}], "prospects", next_url=p3),
                _response([{"id": 3}], "prospects", next_url=None),
            ],
            resume_state=SmartreachResumeConfig(next_url=p2),
        )

        assert result.rows == [{"id": 2}, {"id": 3}]
        # The first-page URL is never fetched on resume — the run starts at the saved cursor.
        assert result.urls == [p2, p3]


class TestVersionDispatch:
    def test_v3_uses_v3_base_root_envelope_and_team_id(self) -> None:
        result = _run(
            [_response_v3([{"id": "p_1"}], "prospects", next_url=None)],
            api_version=SMARTREACH_API_V3,
            smartreach_team_id="team_abc",
        )

        # Rows come from the v3 root envelope; a leftover v1 `data.prospects` selector would yield none.
        assert result.rows == [{"id": "p_1"}]
        assert result.requests[0].url.startswith(f"{SMARTREACH_BASE_URLS[SMARTREACH_API_V3]}/prospects")
        # v3 requires team_id on the first request; the paginator carries it forward via links.next.
        assert result.queries == [{"team_id": ("team_abc",)}]

    def test_v1_uses_v1_base_and_never_sends_team_id(self) -> None:
        # Even if a team_id is threaded through, v1 keeps its legacy base + `data.*` envelope untouched.
        result = _run(
            [_response([{"id": 1}], "prospects", next_url=None)],
            api_version=SMARTREACH_API_V1,
            smartreach_team_id="team_abc",
        )

        assert result.rows == [{"id": 1}]
        assert result.urls == [f"{SMARTREACH_BASE_URL}/prospects"]
        assert result.queries == [{}]


class TestSSRFHostPinning:
    @parameterized.expand(
        [
            ("other_host", "https://evil.example.com/api/v1/prospects"),
            ("subdomain_spoof", "https://api.smartreach.io.evil.com/api/v1/prospects"),
            ("http_downgrade", "http://api.smartreach.io/api/v1/prospects"),
        ]
    )
    def test_off_origin_next_url_is_rejected(self, _name: str, bad_next: str) -> None:
        # Following an off-origin (or scheme-downgraded) cursor would send the user's API key to a host
        # other than SmartReach's own https origin — reject it before the request leaves the process.
        result = _run([_response([{"id": 1}], "prospects", next_url=bad_next)])

        assert isinstance(result.raised, ValueError)
        assert len(result.requests) == 1


class TestRetryAndFailLoud:
    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_fail_loud(self, _name: str, status: int) -> None:
        result = _run([_response(None, "prospects", next_url=None, status=status)])

        assert isinstance(result.raised, requests.HTTPError)


class TestCheckAccess:
    def test_v3_probes_campaigns_with_team_id_on_v3_base(self) -> None:
        # v3 rejects a list request without team_id, so the probe URL must carry it against the v3 base.
        with scripted_network(always(ScriptedResponse(status=200))) as network:
            check_access("uk_test", SMARTREACH_API_V3, smartreach_team_id="team_abc")
        assert [request.url for request in network.requests_log] == [
            f"{SMARTREACH_BASE_URLS[SMARTREACH_API_V3]}/campaigns?team_id=team_abc"
        ]


class TestSmartreachSourceResponse:
    @parameterized.expand([("prospects",), ("campaigns",)])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _run(always(_response(None, endpoint, next_url=None)), endpoint=endpoint).response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Full refresh only: no datetime partitioning is configured.
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in SMARTREACH_ENDPOINTS.values())
        assert set(SMARTREACH_ENDPOINTS) == set(ENDPOINTS)
