import json
from datetime import date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.billomat.billomat import (
    BillomatPaginator,
    BillomatResumeConfig,
    _extract_total_count,
    _format_date,
    validate_credentials as validate_billomat_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.billomat.source import BillomatSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.billomat import (
    BillomatRegisteredAppConfig,
    BillomatSourceConfig,
)


class TestFormatDate:
    def test_none_stays_none(self) -> None:
        assert _format_date(None) is None

    def test_datetime_drops_time_component(self) -> None:
        assert _format_date(datetime(2024, 3, 7, 13, 45, 0)) == "2024-03-07"

    def test_string_passthrough(self) -> None:
        assert _format_date("2024-03-07") == "2024-03-07"


def _make_http_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestExtractTotalCount:
    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"clients": {"client": []}},
            {"clients": {"client": [], "total": "not-a-number"}},
            {"clients": {}, "suppliers": {}},
            [],
        ],
    )
    def test_returns_none_for_missing_or_malformed_total(self, body: Any) -> None:
        assert _extract_total_count(_make_http_response(body)) is None


class TestBillomatPaginator:
    def test_falls_back_to_empty_page_stop_when_total_missing(self) -> None:
        paginator = BillomatPaginator(per_page=100, base_page=1, page=1)
        paginator.update_state(_make_http_response({"clients": {"client": []}}), data=[])
        assert paginator.has_next_page is False


class TestBillomatSourceResumeBehavior:
    """End-to-end pagination/resume behaviour of ``billomat_source`` via ``rest_api_resource``."""

    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(BillomatSource(), BillomatSourceConfig(billomat_id="acme", api_key="test-key"))

    @staticmethod
    def _page(wrapper: str, item: str, row: dict[str, Any], total: str) -> ScriptedResponse:
        return ScriptedResponse(json={wrapper: {item: [row], "total": total}})

    def test_fresh_run_saves_page_after_each_non_terminal_page(self) -> None:
        # `total` (2500) needs 3 pages at the real per_page (1000): pages 1 and 2 leave more
        # records than fetched so far, page 3 covers the rest and stops without a 4th request.
        result = self._driver().run(
            "Clients",
            [
                self._page("clients", "client", {"id": 1}, "2500"),
                self._page("clients", "client", {"id": 2}, "2500"),
                self._page("clients", "client", {"id": 3}, "2500"),
            ],
        )

        assert result.raised is None
        assert result.params("page") == ["1", "2", "3"]
        assert result.rows == [{"id": 1}, {"id": 2}, {"id": 3}]
        assert result.saved_states == [
            BillomatResumeConfig(next_page=2),
            BillomatResumeConfig(next_page=3),
        ]

    def test_resume_seeds_paginator_with_saved_page(self) -> None:
        result = self._driver().run(
            "Clients",
            [self._page("clients", "client", {"id": "50"}, "50")],
            resume_state=BillomatResumeConfig(next_page=5),
        )

        assert result.raised is None
        assert result.params("page") == ["5"]

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        result = self._driver().run("Clients", [self._page("clients", "client", {"id": "1"}, "1")])

        assert result.raised is None
        assert result.params("page") == ["1"]

    @pytest.mark.parametrize(
        ("schema", "path", "wrapper", "item"),
        [
            ("Invoices", "/api/invoices", "invoices", "invoice"),
            ("InvoicePayments", "/api/invoice-payments", "invoice-payments", "invoice-payment"),
            ("Confirmations", "/api/confirmations", "confirmations", "confirmation"),
        ],
    )
    def test_incremental_run_sends_formatted_from_param(self, schema: str, path: str, wrapper: str, item: str) -> None:
        result = self._driver().run(
            schema,
            [self._page(wrapper, item, {"id": "1"}, "1")],
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2024, 5, 1),
        )

        assert result.raised is None
        assert result.paths == [path]
        assert result.requests[0].param("from") == "2024-05-01"
        assert result.requests[0].param("order_by") == "date ASC"
        assert result.rows == [{"id": "1"}]


class TestBillomatClientContactsFanout:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(BillomatSource(), BillomatSourceConfig(billomat_id="acme", api_key="test-key"))

    @staticmethod
    def _clients(*ids: str) -> ScriptedResponse:
        return ScriptedResponse(json={"clients": {"client": [{"id": i} for i in ids], "total": str(len(ids))}})

    @staticmethod
    def _contacts(client_id: str, *ids: str) -> ScriptedResponse:
        rows = [{"id": i, "client_id": client_id} for i in ids]
        return ScriptedResponse(json={"contacts": {"contact": rows, "total": str(len(ids))}})

    def test_fetches_contacts_for_each_client(self) -> None:
        result = self._driver().run(
            "ClientContacts",
            [self._clients("10", "20"), self._contacts("10", "1", "2"), self._contacts("20", "3")],
        )

        assert result.raised is None
        assert result.paths == ["/api/clients", "/api/contacts", "/api/contacts"]
        assert result.params("client_id") == [None, "10", "20"]
        assert result.rows == [
            {"id": "1", "client_id": "10"},
            {"id": "2", "client_id": "10"},
            {"id": "3", "client_id": "20"},
        ]

    def test_resume_skips_clients_already_synced(self) -> None:
        result = self._driver().run(
            "ClientContacts",
            [self._clients("10", "20"), self._contacts("20", "3")],
            resume_state=BillomatResumeConfig(completed=["/contacts?client_id=10"]),
        )

        assert result.raised is None
        assert result.params("client_id") == [None, "20"]
        assert result.rows == [{"id": "3", "client_id": "20"}]


class TestValidateCredentials:
    def test_registered_app_headers_included_when_both_present(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_billomat_credentials("api-key", "acme", "app-1", "app-secret-1") is True

        assert network.requests_log[0].headers["x-appid"] == "app-1"
        assert network.requests_log[0].headers["x-appsecret"] == "app-secret-1"


class TestBillomatSource:
    def setup_method(self) -> None:
        self.source = BillomatSource()
        self.team_id = 123
        self.config = BillomatSourceConfig(billomat_id="acme", api_key="test-key")

    def test_api_docs_url(self) -> None:
        assert self.source.api_docs_url is not None and self.source.api_docs_url.startswith("https://")

    @pytest.mark.parametrize(
        ("billomat_id", "valid"),
        [
            ("acme", True),
            ("acme2024", True),
            ("acme-test", True),
            ("acme.billomat.net", False),
            ("https://acme.billomat.net", False),
            ("-acme", False),
            ("", False),
        ],
    )
    def test_validate_credentials_rejects_non_subdomain_without_calling_the_api(
        self, billomat_id: str, valid: bool
    ) -> None:
        config = BillomatSourceConfig(billomat_id=billomat_id, api_key="key")
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.billomat.source.validate_billomat_credentials"
        ) as mock_validate:
            mock_validate.return_value = True
            is_valid, message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is valid
        if not valid:
            mock_validate.assert_not_called()
            assert message is not None

    @pytest.mark.parametrize(
        ("creds_valid", "expected_valid", "expected_message"),
        [
            (True, True, None),
            (False, False, "Invalid credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.billomat.source.validate_billomat_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        creds_valid: bool,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = creds_valid

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("test-key", "acme", None, None)

    def test_source_for_pipeline_only_passes_last_value_when_incremental(self) -> None:
        result = SourceDriver(self.source, self.config).run(
            "Invoices",
            [ScriptedResponse(json={"invoices": {"invoice": [{"id": "1"}], "total": "1"}})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2024, 1, 1),
        )

        assert result.raised is None
        assert result.requests[0].param("from") == "2024-01-01"

    def test_source_for_pipeline_passes_registered_app_credentials(self) -> None:
        config = BillomatSourceConfig(
            billomat_id="acme",
            api_key="test-key",
            registered_app=BillomatRegisteredAppConfig(app_id="app-1", app_secret="secret-1", enabled=True),
        )
        result = SourceDriver(self.source, config).run(
            "Clients",
            [ScriptedResponse(json={"clients": {"client": [{"id": "1"}], "total": "1"}})],
        )

        assert result.raised is None
        assert result.requests[0].headers["x-appid"] == "app-1"
        assert result.requests[0].headers["x-appsecret"] == "secret-1"
