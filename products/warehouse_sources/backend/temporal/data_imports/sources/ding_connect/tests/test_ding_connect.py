import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ding_connect.ding_connect import (
    DingConnectResumeConfig,
    _flatten_transfer_record,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ding_connect.settings import (
    DING_CONNECT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ding_connect.source import DingConnectSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dingconnect import (
    DingConnectSourceConfig,
)


def _driver(api_key: str = "key") -> SourceDriver:
    return SourceDriver(DingConnectSource(), DingConnectSourceConfig(api_key=api_key))


class TestFlattenTransferRecord:
    def test_missing_transfer_ref_fails_fast(self) -> None:
        # TransferRef is the primary key, so a TransferId object without it must raise rather than
        # silently writing a row with a None primary key.
        with pytest.raises(KeyError):
            _flatten_transfer_record({"TransferId": {"DistributorRef": "DR1"}})


class TestReferenceEndpoints:
    @parameterized.expand(
        [
            ("Countries",),
            ("Currencies",),
            ("Regions",),
            ("Providers",),
            ("ProviderStatus",),
            ("Products",),
            ("ProductDescriptions",),
            ("Promotions",),
            ("ErrorCodeDescriptions",),
        ]
    )
    def test_list_endpoint_yields_items(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json={"Items": [{"a": 1}, {"a": 2}], "ResultCode": 1})])

        # Every bounded lookup reads its rows from the `Items` envelope, so the envelope keys never
        # reach the table and the response is not mistaken for a single-object body like GetBalance.
        assert result.raised is None
        assert result.rows == [{"a": 1}, {"a": 2}]
        # A bounded catalog list comes back in exactly one request.
        assert len(result.requests) == 1

    def test_single_object_endpoint_wraps_one_row(self) -> None:
        result = _driver().run(
            "Balance",
            [ScriptedResponse(json={"Balance": 42.0, "CurrencyIso": "EUR", "ResultCode": 1, "ErrorCodes": []})],
        )

        # GetBalance carries its payload at the top level; it becomes one row with envelope keys stripped.
        assert result.raised is None
        assert result.rows == [{"Balance": 42.0, "CurrencyIso": "EUR"}]


class TestTransferRecordsPagination:
    @staticmethod
    def _page(refs: list[str], there_are_more: bool) -> ScriptedResponse:
        return ScriptedResponse(
            json={
                "Items": [{"TransferId": {"TransferRef": ref, "DistributorRef": f"d-{ref}"}} for ref in refs],
                "ThereAreMoreItems": there_are_more,
                "ResultCode": 1,
                "ErrorCodes": [],
            }
        )

    def test_follows_pagination_until_there_are_no_more_items(self) -> None:
        # Single-item pages (shorter than the page size) keep paging purely on the ThereAreMoreItems
        # flag — proving termination follows the body flag, not page length.
        result = _driver().run(
            "TransferRecords",
            [
                self._page(["TR1"], there_are_more=True),
                self._page(["TR2"], there_are_more=True),
                self._page(["TR3"], there_are_more=False),
            ],
        )

        assert result.raised is None
        assert [row["TransferRef"] for row in result.rows] == ["TR1", "TR2", "TR3"]
        assert [request.json()["Skip"] for request in result.requests] == [0, 100, 200]

    def test_saves_advancing_skip_after_each_non_final_page(self) -> None:
        result = _driver().run(
            "TransferRecords", [self._page(["TR1"], there_are_more=True), self._page(["TR2"], there_are_more=False)]
        )

        # State saved once (after the first page), advancing skip by the page size; the final page
        # saves nothing so a completed sync leaves no stale resume cursor.
        assert result.raised is None
        assert result.saved_states == [DingConnectResumeConfig(skip=100)]

    def test_resumes_from_saved_skip(self) -> None:
        result = _driver().run(
            "TransferRecords",
            [self._page(["TR9"], there_are_more=False)],
            resume_state=DingConnectResumeConfig(skip=200),
        )

        assert result.raised is None
        assert result.requests[0].json()["Skip"] == 200


class TestApiKeyRedaction:
    # The api_key travels in a request header, so every tracked session that carries it must
    # redact its value from HTTP observer logs, captures, and raised error messages.
    def test_client_session_redacts_api_key(self) -> None:
        result = _driver(api_key="secret-key").run("Countries", [ScriptedResponse(json={"Items": [], "ResultCode": 1})])

        assert result.raised is None
        assert result.session_options[0]["redact_values"] == ("secret-key",)
        assert result.requests[0].headers["api_key"] == "secret-key"

    def test_validate_credentials_redacts_api_key(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("secret-key") is True

        assert network.session_options[0]["redact_values"] == ("secret-key",)
        assert network.requests_log[0].headers["api_key"] == "secret-key"


class TestValidateCredentials:
    @parameterized.expand(
        [
            (200, True),
        ]
    )
    def test_status_maps_to_validity(self, status_code: int, expected: bool) -> None:
        # 200 means the api_key was accepted; any other status (401 bad key, 500 transient) is treated
        # as not-yet-valid at source-create.
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("key") is expected

        assert network.requests_log[0].path == "/api/V1/GetBalance"


class TestSourceResponse:
    @parameterized.expand(
        [
            ("Countries", ["CountryIso"], None),
            ("Currencies", ["CurrencyIso"], None),
            ("Regions", ["CountryIso", "RegionCode"], None),
            ("Providers", ["ProviderCode"], None),
            ("ProviderStatus", ["ProviderCode"], None),
            ("Products", ["SkuCode"], None),
            ("ProductDescriptions", ["LocalizationKey", "LanguageCode"], None),
            ("Promotions", ["ProviderCode", "CurrencyIso", "StartUtc"], None),
            ("Balance", ["CurrencyIso"], None),
            ("ErrorCodeDescriptions", ["Code"], None),
            ("TransferRecords", ["TransferRef"], "StartedUtc"),
        ]
    )
    def test_primary_keys_and_partitioning(
        self, endpoint: str, primary_keys: list[str], partition_key: str | None
    ) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json={"Items": []})])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == ([partition_key] if partition_key else None)
        assert response.partition_mode == ("datetime" if partition_key else None)

    def test_only_transfer_records_is_paginated(self) -> None:
        paginated = {name for name, cfg in DING_CONNECT_ENDPOINTS.items() if cfg.paginated}
        assert paginated == {"TransferRecords"}
