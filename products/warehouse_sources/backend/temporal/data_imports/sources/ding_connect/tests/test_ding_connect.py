import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.ding_connect.ding_connect import (
    DingConnectResumeConfig,
    _flatten_transfer_record,
    ding_connect_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ding_connect.settings import (
    DING_CONNECT_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the ding_connect module.
DING_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.ding_connect.ding_connect.make_tracked_session"
)


def _response(body: dict[str, Any]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: DingConnectResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's JSON body AT SEND TIME.

    ``request.json`` is a single dict the paginator mutates in place across pages, so inspecting it
    after the run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    json_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        json_snapshots.append(dict(request.json or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return json_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, api_key: str = "key"):
    return ding_connect_source(api_key, endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


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
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_list_endpoint_yields_items(self, endpoint: str, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"Items": [{"a": 1}, {"a": 2}], "ResultCode": 1})])

        # Every bounded lookup reads its rows from the `Items` envelope, so the envelope keys never
        # reach the table and the response is not mistaken for a single-object body like GetBalance.
        assert _rows(_source(endpoint, _make_manager())) == [{"a": 1}, {"a": 2}]
        # A bounded catalog list comes back in exactly one request.
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_object_endpoint_wraps_one_row(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"Balance": 42.0, "CurrencyIso": "EUR", "ResultCode": 1, "ErrorCodes": []})])

        # GetBalance carries its payload at the top level; it becomes one row with envelope keys stripped.
        assert _rows(_source("Balance", _make_manager())) == [{"Balance": 42.0, "CurrencyIso": "EUR"}]


class TestTransferRecordsPagination:
    def _page(self, refs: list[str], there_are_more: bool) -> Response:
        return _response(
            {
                "Items": [{"TransferId": {"TransferRef": r, "DistributorRef": f"d-{r}"}} for r in refs],
                "ThereAreMoreItems": there_are_more,
                "ResultCode": 1,
                "ErrorCodes": [],
            }
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_pagination_until_there_are_no_more_items(self, MockSession) -> None:
        session = MockSession.return_value
        # Single-item pages (shorter than the page size) keep paging purely on the ThereAreMoreItems
        # flag — proving termination follows the body flag, not page length.
        bodies = _wire(
            session,
            [
                self._page(["TR1"], there_are_more=True),
                self._page(["TR2"], there_are_more=True),
                self._page(["TR3"], there_are_more=False),
            ],
        )

        rows = _rows(_source("TransferRecords", _make_manager()))
        assert [r["TransferRef"] for r in rows] == ["TR1", "TR2", "TR3"]
        assert [b["Skip"] for b in bodies] == [0, 100, 200]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_advancing_skip_after_each_non_final_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [self._page(["TR1"], there_are_more=True), self._page(["TR2"], there_are_more=False)])

        manager = _make_manager()
        _rows(_source("TransferRecords", manager))
        # State saved once (after the first page), advancing skip by the page size; the final page
        # saves nothing so a completed sync leaves no stale resume cursor.
        saved = [c.args[0] for c in manager.save_state.call_args_list]
        assert saved == [DingConnectResumeConfig(skip=100)]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_skip(self, MockSession) -> None:
        session = MockSession.return_value
        bodies = _wire(session, [self._page(["TR9"], there_are_more=False)])

        manager = _make_manager(DingConnectResumeConfig(skip=200))
        _rows(_source("TransferRecords", manager))
        assert bodies[0]["Skip"] == 200


class TestApiKeyRedaction:
    # The api_key travels in a request header, so every tracked session that carries it must
    # redact its value from HTTP observer logs, captures, and raised error messages.
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_session_redacts_api_key(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"Items": [], "ResultCode": 1})])

        _rows(_source("Countries", _make_manager(), api_key="secret-key"))
        assert MockSession.call_args.kwargs["redact_values"] == ("secret-key",)

    @mock.patch(DING_SESSION_PATCH)
    def test_validate_credentials_redacts_api_key(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("secret-key")
        assert mock_session.call_args.kwargs["redact_values"] == ("secret-key",)


class TestValidateCredentials:
    @parameterized.expand([(200, True), (401, False), (500, False)])
    @mock.patch(DING_SESSION_PATCH)
    def test_status_maps_to_validity(self, status_code: int, expected: bool, mock_session) -> None:
        # 200 means the api_key was accepted; any other status (401 bad key, 500 transient) is treated
        # as not-yet-valid at source-create.
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("key") is expected


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
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == ([partition_key] if partition_key else None)
        assert response.partition_mode == ("datetime" if partition_key else None)

    def test_only_transfer_records_is_paginated(self) -> None:
        paginated = {name for name, cfg in DING_CONNECT_ENDPOINTS.items() if cfg.paginated}
        assert paginated == {"TransferRecords"}
