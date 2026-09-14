import json
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any, cast

import pytest
from unittest import mock
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.billomat.billomat import (
    BillomatPaginator,
    BillomatResumeConfig,
    _extract_total_count,
    _format_date,
    billomat_source,
    get_resource,
    validate_credentials as validate_billomat_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.billomat.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.billomat.source import BillomatSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.billomat import (
    BillomatRegisteredAppConfig,
    BillomatSourceConfig,
)

INCREMENTAL_ENDPOINTS = sorted(INCREMENTAL_FIELDS.keys())
FULL_REFRESH_ENDPOINTS = sorted(set(ENDPOINTS) - set(INCREMENTAL_FIELDS.keys()))

# (endpoint, JSON list wrapper key, JSON item key)
_ENDPOINT_JSON_KEYS = {
    "Clients": ("clients", "client"),
    "Suppliers": ("suppliers", "supplier"),
    "Invoices": ("invoices", "invoice"),
    "Estimates": ("offers", "offer"),
    "CreditNotes": ("credit-notes", "credit-note"),
    "Incomings": ("incomings", "incoming"),
}


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "Clients",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 123,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestFormatDate:
    def test_none_stays_none(self) -> None:
        assert _format_date(None) is None

    def test_date_formats_as_iso(self) -> None:
        assert _format_date(date(2024, 3, 7)) == "2024-03-07"

    def test_datetime_drops_time_component(self) -> None:
        assert _format_date(datetime(2024, 3, 7, 13, 45, 0)) == "2024-03-07"

    def test_string_passthrough(self) -> None:
        assert _format_date("2024-03-07") == "2024-03-07"


class TestGetResource:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_resource_shape(self, endpoint: str) -> None:
        list_key, item_key = _ENDPOINT_JSON_KEYS[endpoint]
        resource = get_resource(endpoint, should_use_incremental_field=False)

        assert resource["name"] == endpoint
        assert resource["table_format"] == "delta"
        endpoint_config = cast(dict[str, Any], resource["endpoint"])
        assert endpoint_config["data_selector"] == f'"{list_key}"."{item_key}"'
        assert endpoint_config["params"]["per_page"] == 1000

    @pytest.mark.parametrize("endpoint", FULL_REFRESH_ENDPOINTS)
    def test_full_refresh_endpoints_always_replace(self, endpoint: str) -> None:
        for should_use_incremental_field in (False, True):
            resource = get_resource(endpoint, should_use_incremental_field=should_use_incremental_field)
            assert resource["write_disposition"] == "replace"
            endpoint_config = cast(dict[str, Any], resource["endpoint"])
            assert "from" not in endpoint_config["params"]

    @pytest.mark.parametrize("endpoint", INCREMENTAL_ENDPOINTS)
    def test_incremental_endpoint_disabled_is_full_refresh(self, endpoint: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=False)
        assert resource["write_disposition"] == "replace"
        endpoint_config = cast(dict[str, Any], resource["endpoint"])
        # The key is present (as a static None, filtered out before the request) but not an
        # active incremental param, so no unbounded `from` filter leaks into a full sync.
        assert endpoint_config["params"]["from"] is None

    @pytest.mark.parametrize("endpoint", INCREMENTAL_ENDPOINTS)
    def test_incremental_endpoint_enabled_uses_merge(self, endpoint: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=True)
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        endpoint_config = cast(dict[str, Any], resource["endpoint"])
        assert endpoint_config["params"]["from"]["type"] == "incremental"
        assert endpoint_config["params"]["from"]["convert"] is _format_date


def _make_http_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestExtractTotalCount:
    def test_reads_total_from_single_wrapper_key(self) -> None:
        response = _make_http_response({"clients": {"client": [{"id": 1}], "total": "12"}})
        assert _extract_total_count(response) == 12

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
    def test_stops_once_page_times_per_page_covers_total(self) -> None:
        paginator = BillomatPaginator(per_page=100, base_page=1, page=1)
        paginator.update_state(_make_http_response({"clients": {"client": [{"id": 1}], "total": "100"}}))
        assert paginator.has_next_page is False

    def test_continues_while_total_exceeds_pages_fetched(self) -> None:
        paginator = BillomatPaginator(per_page=100, base_page=1, page=1)
        paginator.update_state(
            _make_http_response({"clients": {"client": [{"id": 1}], "total": "250"}}), data=[{"id": 1}]
        )
        assert paginator.has_next_page is True
        assert paginator.page == 2

    def test_falls_back_to_empty_page_stop_when_total_missing(self) -> None:
        paginator = BillomatPaginator(per_page=100, base_page=1, page=1)
        paginator.update_state(_make_http_response({"clients": {"client": []}}), data=[])
        assert paginator.has_next_page is False

    def test_does_not_stop_early_when_total_missing_and_page_has_data(self) -> None:
        paginator = BillomatPaginator(per_page=100, base_page=1, page=1)
        paginator.update_state(_make_http_response({"clients": {"client": [{"id": 1}]}}), data=[{"id": 1}])
        assert paginator.has_next_page is True


class TestBillomatSourceResumeBehavior:
    """End-to-end pagination/resume behaviour of ``billomat_source`` via ``rest_api_resource``."""

    def _drive(
        self,
        endpoint: str,
        manager: MagicMock,
        responses: list[Response],
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
    ) -> tuple[MagicMock, list[dict[str, Any]]]:
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.billomat.billomat.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            resource = billomat_source(
                api_key="test-key",
                billomat_id="acme",
                app_id=None,
                app_secret=None,
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                db_incremental_field_last_value=db_incremental_field_last_value,
                should_use_incremental_field=should_use_incremental_field,
            )
            list(cast(Iterable[Any], resource))
            return mock_session, sent_params

    def test_fresh_run_saves_page_after_each_non_terminal_page(self) -> None:
        # `total` (2500) needs 3 pages at the real per_page (1000): pages 1 and 2 leave more
        # records than fetched so far, page 3 covers the rest and stops without a 4th request.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response({"clients": {"client": [{"id": 1}], "total": "2500"}}),
            _make_http_response({"clients": {"client": [{"id": 2}], "total": "2500"}}),
            _make_http_response({"clients": {"client": [{"id": 3}], "total": "2500"}}),
        ]
        _, sent_params = self._drive("Clients", manager, responses)

        assert [p.get("page") for p in sent_params] == [1, 2, 3]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            BillomatResumeConfig(next_page=2),
            BillomatResumeConfig(next_page=3),
        ]

    def test_single_item_result_is_not_dropped(self) -> None:
        # Billomat's XML-to-JSON conversion collapses a one-item list to a bare object instead
        # of a one-element array — the extraction must still yield exactly one row.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = iter([_make_http_response({"clients": {"client": {"id": 42}, "total": "1"}})])
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.billomat.billomat.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = lambda *args, **kwargs: next(responses)

            resource = billomat_source(
                api_key="test-key",
                billomat_id="acme",
                app_id=None,
                app_secret=None,
                endpoint="Clients",
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                db_incremental_field_last_value=None,
                should_use_incremental_field=False,
            )
            batches = list(cast(Iterable[Any], resource))

        # One page yielded as one batch; the item that came back as a bare object (not a
        # one-element array) must still land as a single row, not be dropped or double-wrapped.
        assert batches == [[{"id": 42}]]

    def test_terminal_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"clients": {"client": [{"id": "only"}], "total": "1"}})]
        self._drive("Clients", manager, responses)

        manager.save_state.assert_not_called()

    def test_resume_seeds_paginator_with_saved_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = BillomatResumeConfig(next_page=5)

        responses = [_make_http_response({"clients": {"client": [{"id": "50"}], "total": "50"}})]
        _, sent_params = self._drive("Clients", manager, responses)

        assert [p.get("page") for p in sent_params] == [5]
        manager.load_state.assert_called_once()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"clients": {"client": [{"id": "1"}], "total": "1"}})]
        self._drive("Clients", manager, responses)

        manager.load_state.assert_not_called()

    def test_incremental_run_sends_formatted_from_param(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"invoices": {"invoice": [{"id": "1"}], "total": "1"}})]
        _, sent_params = self._drive(
            "Invoices",
            manager,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2024, 5, 1),
        )

        assert sent_params[0]["from"] == "2024-05-01"

    def test_full_refresh_run_omits_from_param(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"invoices": {"invoice": [{"id": "1"}], "total": "1"}})]
        _, sent_params = self._drive("Invoices", manager, responses, should_use_incremental_field=False)

        assert "from" not in sent_params[0]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [(200, True), (401, False), (403, False), (500, False)],
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.billomat.billomat.make_tracked_session")
    def test_status_maps_to_validity(self, mock_session_factory: MagicMock, status_code: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status_code
        mock_session_factory.return_value.get.return_value = response

        assert validate_billomat_credentials("api-key", "acme", None, None) is expected

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.billomat.billomat.make_tracked_session")
    def test_probes_clients_endpoint(self, mock_session_factory: MagicMock) -> None:
        mock_session_factory.return_value.get.return_value = MagicMock(status_code=200)

        validate_billomat_credentials("api-key", "acme", None, None)

        mock_session_factory.return_value.get.assert_called_once_with(
            "https://acme.billomat.net/api/clients?per_page=1"
        )

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.billomat.billomat.make_tracked_session")
    def test_registered_app_headers_included_when_both_present(self, mock_session_factory: MagicMock) -> None:
        mock_session_factory.return_value.get.return_value = MagicMock(status_code=200)

        validate_billomat_credentials("api-key", "acme", "app-1", "app-secret-1")

        headers = mock_session_factory.call_args.kwargs["headers"]
        assert headers["X-AppId"] == "app-1"
        assert headers["X-AppSecret"] == "app-secret-1"

    @pytest.mark.parametrize(("app_id", "app_secret"), [(None, "app-secret-1"), ("app-1", None), (None, None)])
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.billomat.billomat.make_tracked_session")
    def test_registered_app_headers_omitted_unless_both_present(
        self, mock_session_factory: MagicMock, app_id: str | None, app_secret: str | None
    ) -> None:
        mock_session_factory.return_value.get.return_value = MagicMock(status_code=200)

        validate_billomat_credentials("api-key", "acme", app_id, app_secret)

        headers = mock_session_factory.call_args.kwargs["headers"]
        assert "X-AppId" not in headers
        assert "X-AppSecret" not in headers


class TestBillomatSource:
    def setup_method(self) -> None:
        self.source = BillomatSource()
        self.team_id = 123
        self.config = BillomatSourceConfig(billomat_id="acme", api_key="test-key")

    def test_billomat_id_is_a_connection_host_field(self) -> None:
        # billomat_id determines the request host (https://{billomat_id}.billomat.net), so
        # changing it must force re-entry of the stored api_key/app_secret.
        assert self.source.connection_host_fields == ["billomat_id"]

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

    def test_validate_credentials_passes_registered_app(self) -> None:
        config = BillomatSourceConfig(
            billomat_id="acme",
            api_key="test-key",
            registered_app=BillomatRegisteredAppConfig(app_id="app-1", app_secret="secret-1", enabled=True),
        )
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.billomat.source.validate_billomat_credentials"
        ) as mock_validate:
            mock_validate.return_value = True
            self.source.validate_credentials(config, self.team_id)

        mock_validate.assert_called_once_with("test-key", "acme", "app-1", "secret-1")

    def test_validate_credentials_ignores_disabled_registered_app(self) -> None:
        config = BillomatSourceConfig(
            billomat_id="acme",
            api_key="test-key",
            registered_app=BillomatRegisteredAppConfig(app_id="app-1", app_secret="secret-1", enabled=False),
        )
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.billomat.source.validate_billomat_credentials"
        ) as mock_validate:
            mock_validate.return_value = True
            self.source.validate_credentials(config, self.team_id)

        mock_validate.assert_called_once_with("test-key", "acme", None, None)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.billomat.source.billomat_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(schema_name="Invoices", team_id=99, job_id="job-xyz")
        manager = mock.MagicMock(spec=ResumableSourceManager)

        response = self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            api_key="test-key",
            billomat_id="acme",
            app_id=None,
            app_secret=None,
            endpoint="Invoices",
            team_id=99,
            job_id="job-xyz",
            resumable_source_manager=manager,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        assert response.primary_keys == ["id"]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.billomat.source.billomat_source")
    def test_source_for_pipeline_only_passes_last_value_when_incremental(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(
            schema_name="Invoices",
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2024, 1, 1),
        )
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] == date(2024, 1, 1)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.billomat.source.billomat_source")
    def test_source_for_pipeline_passes_registered_app_credentials(self, mock_source: mock.MagicMock) -> None:
        config = BillomatSourceConfig(
            billomat_id="acme",
            api_key="test-key",
            registered_app=BillomatRegisteredAppConfig(app_id="app-1", app_secret="secret-1", enabled=True),
        )
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(config, manager, _make_inputs())

        assert mock_source.call_args.kwargs["app_id"] == "app-1"
        assert mock_source.call_args.kwargs["app_secret"] == "secret-1"
