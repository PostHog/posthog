from typing import Any

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.ding_connect import ding_connect
from products.warehouse_sources.backend.temporal.data_imports.sources.ding_connect.ding_connect import (
    DingConnectResumeConfig,
    _flatten_transfer_record,
    _row_from_single_object,
    ding_connect_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ding_connect.settings import (
    DING_CONNECT_ENDPOINTS,
)


class _FakeResumableManager:
    def __init__(self, state: DingConnectResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[DingConnectResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> DingConnectResumeConfig | None:
        return self._state

    def save_state(self, data: DingConnectResumeConfig) -> None:
        self.saved.append(data)


def _collect(endpoint: str, responses: list[dict[str, Any]], manager: _FakeResumableManager, monkeypatch: Any) -> list:
    """Run get_rows against a queue of canned envelope responses, flattening yielded pages to rows."""
    queue = list(responses)

    def fake_request(session: Any, method: str, url: str, headers: dict, logger: Any, json_body: Any = None) -> dict:
        return queue.pop(0)

    monkeypatch.setattr(ding_connect, "_request", fake_request)
    monkeypatch.setattr(ding_connect, "make_tracked_session", lambda **kwargs: MagicMock())

    rows: list = []
    for page in get_rows("key", endpoint, MagicMock(), manager):  # type: ignore[arg-type]
        rows.extend(page)
    return rows


class TestFlattenTransferRecord:
    def test_lifts_transfer_id_fields_to_top_level(self) -> None:
        record = {"TransferId": {"TransferRef": "TR1", "DistributorRef": "DR1"}, "SkuCode": "SKU"}
        flattened = _flatten_transfer_record(record)
        assert flattened["TransferRef"] == "TR1"
        assert flattened["DistributorRef"] == "DR1"
        assert flattened["SkuCode"] == "SKU"

    def test_missing_transfer_id_is_left_untouched(self) -> None:
        record = {"SkuCode": "SKU"}
        assert _flatten_transfer_record(record) == {"SkuCode": "SKU"}

    def test_missing_transfer_ref_fails_fast(self) -> None:
        # TransferRef is the primary key, so a TransferId object without it must raise rather than
        # silently writing a row with a None primary key.
        with pytest.raises(KeyError):
            _flatten_transfer_record({"TransferId": {"DistributorRef": "DR1"}})


class TestRowFromSingleObject:
    def test_strips_envelope_keys(self) -> None:
        body = {"Balance": 100.5, "CurrencyIso": "USD", "ResultCode": 1, "ErrorCodes": []}
        assert _row_from_single_object(body) == {"Balance": 100.5, "CurrencyIso": "USD"}


class TestReferenceEndpoints:
    def test_list_endpoint_yields_items(self, monkeypatch: Any) -> None:
        responses = [{"Items": [{"CountryIso": "GB"}, {"CountryIso": "US"}], "ResultCode": 1, "ErrorCodes": []}]
        rows = _collect("Countries", responses, _FakeResumableManager(), monkeypatch)
        assert rows == [{"CountryIso": "GB"}, {"CountryIso": "US"}]

    def test_empty_list_yields_nothing(self, monkeypatch: Any) -> None:
        responses = [{"Items": [], "ResultCode": 1, "ErrorCodes": []}]
        rows = _collect("Currencies", responses, _FakeResumableManager(), monkeypatch)
        assert rows == []

    def test_single_object_endpoint_wraps_one_row(self, monkeypatch: Any) -> None:
        responses = [{"Balance": 42.0, "CurrencyIso": "EUR", "ResultCode": 1, "ErrorCodes": []}]
        rows = _collect("Balance", responses, _FakeResumableManager(), monkeypatch)
        assert rows == [{"Balance": 42.0, "CurrencyIso": "EUR"}]

    def test_reference_endpoint_does_not_save_resume_state(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        responses = [{"Items": [{"ProviderCode": "P1"}], "ResultCode": 1, "ErrorCodes": []}]
        _collect("Providers", responses, manager, monkeypatch)
        assert manager.saved == []


class TestTransferRecordsPagination:
    def _page(self, refs: list[str], there_are_more: bool) -> dict[str, Any]:
        return {
            "Items": [{"TransferId": {"TransferRef": r, "DistributorRef": f"d-{r}"}} for r in refs],
            "ThereAreMoreItems": there_are_more,
            "ResultCode": 1,
            "ErrorCodes": [],
        }

    def test_single_page_flattens_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = _collect("TransferRecords", [self._page(["TR1", "TR2"], there_are_more=False)], manager, monkeypatch)
        assert [r["TransferRef"] for r in rows] == ["TR1", "TR2"]
        # Only one page, so there's nothing further to resume to.
        assert manager.saved == []

    def test_follows_pagination_until_there_are_no_more_items(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        responses = [
            self._page(["TR1"], there_are_more=True),
            self._page(["TR2"], there_are_more=True),
            self._page(["TR3"], there_are_more=False),
        ]
        rows = _collect("TransferRecords", responses, manager, monkeypatch)
        assert [r["TransferRef"] for r in rows] == ["TR1", "TR2", "TR3"]

    def test_saves_advancing_skip_after_each_non_final_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        responses = [
            self._page(["TR1"], there_are_more=True),
            self._page(["TR2"], there_are_more=False),
        ]
        _collect("TransferRecords", responses, manager, monkeypatch)
        # State saved once (after the first page), advancing skip by the page size; the final page
        # saves nothing so a completed sync leaves no stale resume cursor.
        assert [c.skip for c in manager.saved] == [ding_connect.TRANSFER_RECORDS_PAGE_SIZE]

    def test_resumes_from_saved_skip(self, monkeypatch: Any) -> None:
        seen_skips: list[int] = []

        def fake_request(
            session: Any, method: str, url: str, headers: dict, logger: Any, json_body: Any = None
        ) -> dict:
            seen_skips.append(json_body["Skip"])
            return self._page(["TR9"], there_are_more=False)

        monkeypatch.setattr(ding_connect, "_request", fake_request)
        monkeypatch.setattr(ding_connect, "make_tracked_session", lambda **kwargs: MagicMock())

        manager = _FakeResumableManager(DingConnectResumeConfig(skip=200))
        list(get_rows("key", "TransferRecords", MagicMock(), manager))  # type: ignore[arg-type]
        assert seen_skips == [200]


class TestValidateCredentials:
    def test_status_maps_to_validity(self, monkeypatch: Any) -> None:
        # 200 means the api_key was accepted; any other status (401 bad key, 500 transient) is treated
        # as not-yet-valid at source-create.
        for status_code, expected in [(200, True), (401, False), (500, False)]:
            session = MagicMock()
            session.get.return_value = MagicMock(status_code=status_code)
            monkeypatch.setattr(ding_connect, "make_tracked_session", lambda *args, session=session, **kwargs: session)
            assert validate_credentials("key") is expected

    def test_network_error_is_invalid(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        monkeypatch.setattr(ding_connect, "make_tracked_session", lambda **kwargs: session)
        assert validate_credentials("key") is False


class TestApiKeyRedaction:
    # The api_key travels in a request header, so every tracked session that carries it must
    # redact it from HTTP observer logs and captures.
    def test_get_rows_redacts_api_key(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_make_tracked_session(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return MagicMock()

        monkeypatch.setattr(ding_connect, "make_tracked_session", fake_make_tracked_session)
        monkeypatch.setattr(
            ding_connect,
            "_request",
            lambda *args, **kwargs: {"Items": [], "ResultCode": 1, "ErrorCodes": []},
        )

        list(get_rows("secret-key", "Countries", MagicMock(), _FakeResumableManager()))  # type: ignore[arg-type]
        assert captured["redact_values"] == ("secret-key",)

    def test_validate_credentials_redacts_api_key(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_make_tracked_session(**kwargs: Any) -> Any:
            captured.update(kwargs)
            session = MagicMock()
            session.get.return_value = MagicMock(status_code=200)
            return session

        monkeypatch.setattr(ding_connect, "make_tracked_session", fake_make_tracked_session)

        validate_credentials("secret-key")
        assert captured["redact_values"] == ("secret-key",)


class TestSourceResponse:
    @parameterized.expand(
        [
            ("Countries", ["CountryIso"], None),
            ("Currencies", ["CurrencyIso"], None),
            ("Providers", ["ProviderCode"], None),
            ("Products", ["SkuCode"], None),
            ("Promotions", ["ProviderCode", "CurrencyIso", "StartUtc"], None),
            ("Balance", ["CurrencyIso"], None),
            ("TransferRecords", ["TransferRef"], "StartedUtc"),
        ]
    )
    def test_primary_keys_and_partitioning(
        self, endpoint: str, primary_keys: list[str], partition_key: str | None
    ) -> None:
        response = ding_connect_source("key", endpoint, MagicMock(), MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == ([partition_key] if partition_key else None)
        assert response.partition_mode == ("datetime" if partition_key else None)

    def test_only_transfer_records_is_paginated(self) -> None:
        paginated = {name for name, cfg in DING_CONNECT_ENDPOINTS.items() if cfg.paginated}
        assert paginated == {"TransferRecords"}
