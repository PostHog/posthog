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
    validate_credentials as validate_billomat_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.billomat.source import BillomatSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.billomat import (
    BillomatRegisteredAppConfig,
    BillomatSourceConfig,
)


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


class TestValidateCredentials:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.billomat.billomat.make_tracked_session")
    def test_registered_app_headers_included_when_both_present(self, mock_session_factory: MagicMock) -> None:
        mock_session_factory.return_value.get.return_value = MagicMock(status_code=200)

        validate_billomat_credentials("api-key", "acme", "app-1", "app-secret-1")

        headers = mock_session_factory.call_args.kwargs["headers"]
        assert headers["X-AppId"] == "app-1"
        assert headers["X-AppSecret"] == "app-secret-1"


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
