from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.care_quality_commission import (
    care_quality_commission as cqc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.care_quality_commission.care_quality_commission import (
    CQC_BASE_URL,
    CQCResumeConfig,
    _build_url,
    _fetch,
    _get_headers,
    get_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.care_quality_commission.settings import (
    CQC_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.care_quality_commission.source import (
    CareQualityCommissionSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common import boundary_checkpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.carequalitycommission import (
    CareQualityCommissionSourceConfig,
)


def _driver(partner_code: str | None = "PC") -> SourceDriver:
    return SourceDriver(
        CareQualityCommissionSource(), CareQualityCommissionSourceConfig(api_key="key", partner_code=partner_code)
    )


def _rows(result: DriveResult) -> list[dict[str, Any]]:
    return [row for table in result.items for row in table.to_pylist()]


class _FakeResumableManager:
    def __init__(self, state: CQCResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[CQCResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> CQCResumeConfig | None:
        return self._state

    def save_state(self, data: CQCResumeConfig) -> None:
        self.saved.append(data)


class TestGetHeaders:
    def test_uses_subscription_key_header(self) -> None:
        headers = _get_headers("my-key")
        # CQC authenticates with the Azure API Management subscription-key header, not a bearer token.
        assert headers["Ocp-Apim-Subscription-Key"] == "my-key"
        assert headers["Accept"] == "application/json"


class TestBuildUrl:
    def test_no_params(self) -> None:
        assert _build_url("/providers/1-123", {}) == f"{CQC_BASE_URL}/providers/1-123"


class TestFetch:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_raises_retryable_error(self, _name: str, status: int) -> None:
        response = MagicMock()
        response.status_code = status
        session = MagicMock()
        session.get.return_value = response
        # Skip tenacity's backoff sleeps so the 5 retries don't slow the test.
        _fetch.retry.sleep = lambda _s: None  # type: ignore[attr-defined]
        with pytest.raises(cqc.CQCRetryableError):
            _fetch(session, "http://x", {}, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_error_raises_for_status(self, _name: str, status: int) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = False
        response.raise_for_status.side_effect = requests.HTTPError(f"{status} error", response=response)
        session = MagicMock()
        session.get.return_value = response
        with pytest.raises(requests.HTTPError):
            _fetch(session, "http://x", {}, MagicMock())

    def test_success_returns_json(self) -> None:
        response = MagicMock()
        response.status_code = 200
        response.ok = True
        response.json.return_value = {"providers": []}
        session = MagicMock()
        session.get.return_value = response
        assert _fetch(session, "http://x", {}, MagicMock()) == {"providers": []}


def _collect(
    manager: _FakeResumableManager,
    monkeypatch: Any,
    pages: dict[str, Any],
    endpoint: str = "providers",
    partner_code: str | None = "PC",
) -> list[dict]:
    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
        result = pages[url]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(cqc, "_fetch", fake_fetch)
    monkeypatch.setattr(cqc, "make_tracked_session", lambda **kwargs: MagicMock())

    rows: list[dict] = []
    for table in get_rows(
        api_key="key",
        partner_code=partner_code,
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        rows.extend(table.to_pylist())
    return rows


class TestGetRowsFanOut:
    def test_paginates_across_pages(self, monkeypatch: Any) -> None:
        pages = {
            f"{CQC_BASE_URL}/providers?page=1&perPage=500&partnerCode=PC": {
                "providers": [{"providerId": "1-A"}],
                "totalPages": 2,
            },
            f"{CQC_BASE_URL}/providers/1-A?partnerCode=PC": {"providerId": "1-A"},
            f"{CQC_BASE_URL}/providers?page=2&perPage=500&partnerCode=PC": {
                "providers": [{"providerId": "1-B"}],
                "totalPages": 2,
            },
            f"{CQC_BASE_URL}/providers/1-B?partnerCode=PC": {"providerId": "1-B"},
        }
        manager = _FakeResumableManager()
        monkeypatch.setattr(boundary_checkpoint, "PARTIAL_FLUSH_INTERVAL_SECONDS", 0)
        rows = _collect(manager, monkeypatch, pages)
        assert rows == [{"providerId": "1-A"}, {"providerId": "1-B"}]
        # The bookmark advances to page 2 after page 1 completes so a crash resumes mid-stream.
        assert CQCResumeConfig(page=2) in manager.saved

    def test_paginates_when_total_pages_missing(self) -> None:
        # The API omits totalPages: don't trust the fallback to terminate after page 1 — keep
        # paging until an empty page is returned.
        result = _driver().run(
            "providers",
            [
                ScriptedResponse(json={"providers": [{"providerId": "1-A"}]}),
                ScriptedResponse(json={"providerId": "1-A"}),
                ScriptedResponse(json={"providers": [{"providerId": "1-B"}]}),
                ScriptedResponse(json={"providerId": "1-B"}),
                ScriptedResponse(json={"providers": []}),
            ],
        )
        assert result.raised is None
        assert _rows(result) == [{"providerId": "1-A"}, {"providerId": "1-B"}]
        assert result.params("page") == ["1", None, "2", None, "3"]

    def test_record_without_id_raises(self) -> None:
        # A list record missing its id field is an API contract violation — fail fast with a
        # KeyError rather than silently dropping the row.
        result = _driver().run(
            "providers", [ScriptedResponse(json={"providers": [{"name": "no id"}], "totalPages": 1})]
        )
        assert isinstance(result.raised, KeyError)
        assert result.paths == ["/public/v1/providers"]

    def test_resume_skips_already_synced_pages(self) -> None:
        # Saved state says page 2; page 1 must not be fetched again.
        result = _driver().run(
            "providers",
            [
                ScriptedResponse(json={"providers": [{"providerId": "1-B"}], "totalPages": 2}),
                ScriptedResponse(json={"providerId": "1-B"}),
            ],
            resume_state=CQCResumeConfig(page=2),
        )
        assert result.raised is None
        assert _rows(result) == [{"providerId": "1-B"}]
        assert result.paths == ["/public/v1/providers", "/public/v1/providers/1-B"]
        assert result.params("page") == ["2", None]

    def test_omits_partner_code_when_absent(self) -> None:
        result = _driver(partner_code=None).run(
            "providers",
            [
                ScriptedResponse(json={"providers": [{"providerId": "1-A"}], "totalPages": 1}),
                ScriptedResponse(json={"providerId": "1-A"}),
            ],
        )
        assert result.raised is None
        assert _rows(result) == [{"providerId": "1-A"}]
        assert result.params("partnerCode") == [None, None]


class TestGetRowsInspectionAreas:
    def test_unpaginated_endpoint_fetches_a_single_page(self) -> None:
        # The taxonomy endpoint ignores page/perPage and re-serves the whole table, so a request
        # for page 2 would duplicate every row forever. Only page 1 is registered here, so a
        # second fetch fails the test.
        result = _driver().run(
            "inspection_areas",
            [ScriptedResponse(json={"inspectionAreas": [{"inspectionAreaId": "IA-1"}, {"inspectionAreaId": "IA-2"}]})],
        )
        assert result.raised is None
        assert _rows(result) == [{"inspectionAreaId": "IA-1"}, {"inspectionAreaId": "IA-2"}]
        assert result.paths == ["/public/v1/inspection-areas"]
        assert result.params("page") == [None]
        assert result.params("perPage") == [None]

    @pytest.mark.parametrize(
        "endpoint,collection,id_field,org_id",
        [
            ("provider_inspection_areas", "providers", "providerId", "1-P"),
            ("location_inspection_areas", "locations", "locationId", "1-L"),
        ],
    )
    def test_nested_rows_carry_the_parent_id(self, endpoint: str, collection: str, id_field: str, org_id: str) -> None:
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json={collection: [{id_field: org_id}], "totalPages": 1}),
                ScriptedResponse(
                    json={
                        "inspectionAreas": [
                            {"inspectionAreaId": "IA-1", "status": "Active"},
                            {"inspectionAreaId": "IA-2", "status": "Superseded"},
                        ]
                    }
                ),
            ],
        )
        assert result.raised is None
        assert result.paths == [f"/public/v1/{collection}", f"/public/v1/{collection}/{org_id}/inspection-areas"]
        # The same inspectionAreaId recurs across organisations, so the parent id has to land on
        # the row for the composite primary key to identify it.
        assert _rows(result) == [
            {id_field: org_id, "inspectionAreaId": "IA-1", "status": "Active"},
            {id_field: org_id, "inspectionAreaId": "IA-2", "status": "Superseded"},
        ]

    def test_organisation_without_inspection_areas_is_skipped(self) -> None:
        # Most organisations have no inspected areas, so an empty or absent list is routine — it
        # must not stop the sweep over the remaining organisations.
        result = _driver().run(
            "provider_inspection_areas",
            [
                ScriptedResponse(
                    json={
                        "providers": [{"providerId": "1-A"}, {"providerId": "1-B"}, {"providerId": "1-C"}],
                        "totalPages": 1,
                    }
                ),
                ScriptedResponse(json={"inspectionAreas": []}),
                ScriptedResponse(json={}),
                ScriptedResponse(json={"inspectionAreas": [{"inspectionAreaId": "IA-1"}]}),
            ],
        )
        assert result.raised is None
        assert result.paths == [
            "/public/v1/providers",
            "/public/v1/providers/1-A/inspection-areas",
            "/public/v1/providers/1-B/inspection-areas",
            "/public/v1/providers/1-C/inspection-areas",
        ]
        assert _rows(result) == [{"providerId": "1-C", "inspectionAreaId": "IA-1"}]


class TestSourceResponse:
    @parameterized.expand([("providers", ["providerId"]), ("locations", ["locationId"])])
    def test_response_shape(self, endpoint: str, expected_keys: list[str]) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json={endpoint: []})])
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        # Partition on the stable registration date so partitions never rewrite.
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [CQC_ENDPOINTS[endpoint].partition_key]

    @parameterized.expand(
        [
            ("inspection_areas", ["inspectionAreaId"]),
            ("provider_inspection_areas", ["providerId", "inspectionAreaId"]),
            ("location_inspection_areas", ["locationId", "inspectionAreaId"]),
        ]
    )
    def test_inspection_area_responses_are_unpartitioned(self, endpoint: str, expected_keys: list[str]) -> None:
        collection = (
            "inspectionAreas"
            if endpoint == "inspection_areas"
            else "providers"
            if endpoint == "provider_inspection_areas"
            else "locations"
        )
        result = _driver().run(endpoint, [ScriptedResponse(json={collection: []})])
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.primary_keys == expected_keys
        # Inspection-area rows carry no stable creation date, so there is nothing safe to
        # partition on — `endDate` and the retirement dates both move when CQC retires an area.
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            assert cqc.validate_credentials("key", "PC") is expected
        assert len(network.requests_log) == 1
        request = network.requests_log[0]
        assert request.path == "/public/v1/providers"
        assert request.param("page") == "1"
        assert request.param("perPage") == "1"
        assert request.param("partnerCode") == "PC"
        assert request.headers["ocp-apim-subscription-key"] == "key"
        assert network.session_options == [{"redact_values": ("key",), "allow_redirects": False}]

    def test_network_error_is_invalid(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))) as network:
            assert cqc.validate_credentials("key", "PC") is False
        assert {request.path for request in network.requests_log} == {"/public/v1/providers"}
