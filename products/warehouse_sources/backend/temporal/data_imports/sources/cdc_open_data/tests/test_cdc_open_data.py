import json
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.cdc_open_data.cdc_open_data import (
    CdcOpenDataResumeConfig,
    _auth_config,
    _format_where_value,
    _probe_url,
    cdc_open_data_source,
    validate_cdc_open_data_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cdc_open_data.settings import PAGE_SIZE
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


class TestFormatWhereValue:
    @parameterized.expand(
        [
            ("naive_datetime", datetime(2024, 6, 1, 12, 30, 0), "2024-06-01T12:30:00"),
            (
                "aware_datetime_converted_to_utc",
                datetime(2024, 6, 1, 12, 30, 0, tzinfo=UTC) + timedelta(hours=0),
                "2024-06-01T12:30:00",
            ),
            ("date_only", date(2024, 6, 1), "2024-06-01T00:00:00"),
            ("string_passthrough", "2024-06-01T12:30:00", "2024-06-01T12:30:00"),
        ]
    )
    def test_formats_value_for_soql_comparison(self, _name: str, value: Any, expected: str) -> None:
        assert _format_where_value(value) == expected


class TestAuthConfig:
    def test_no_app_token_means_anonymous_request(self) -> None:
        assert _auth_config("") is None

    def test_app_token_becomes_header_auth(self) -> None:
        auth = _auth_config("my-token")
        assert auth == {"type": "api_key", "api_key": "my-token", "name": "X-App-Token", "location": "header"}


class TestProbeUrl:
    def test_probe_url_targets_dataset_resource_with_limit_one(self) -> None:
        url = _probe_url("9bhg-hcku")
        assert url == "https://data.cdc.gov/resource/9bhg-hcku.json?%24limit=1"


def _make_http_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestValidateCdcOpenDataCredentials:
    @parameterized.expand(
        [
            ("reachable", 200, (True, None)),
            (
                "missing_dataset",
                404,
                (
                    False,
                    "Dataset 'aaaa-aaaa' was not found on data.cdc.gov. Check the dataset ID in its data.cdc.gov URL.",
                ),
            ),
            (
                "invalid_app_token",
                403,
                (
                    False,
                    "Invalid CDC Open Data app token. Check the token, or leave it blank to use the shared public pool.",
                ),
            ),
            (
                "unreachable",
                None,
                (False, "Could not reach data.cdc.gov. Check your network connection and try again."),
            ),
            ("unexpected_status", 500, (False, "data.cdc.gov returned HTTP 500 for dataset 'aaaa-aaaa'.")),
        ]
    )
    def test_maps_probe_status_to_message(
        self, _name: str, probe_status: int | None, expected: tuple[bool, str | None]
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.cdc_open_data.cdc_open_data.validate_via_probe",
            return_value=(probe_status == 200, probe_status),
        ):
            assert validate_cdc_open_data_credentials("some-token", "aaaa-aaaa") == expected

    def test_redacts_app_token_from_captured_samples(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.cdc_open_data.cdc_open_data.validate_via_probe",
            return_value=(True, 200),
        ) as mock_probe:
            validate_cdc_open_data_credentials("super-secret-token", "9bhg-hcku")
        session_factory = mock_probe.call_args.args[0]
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.cdc_open_data.cdc_open_data.make_tracked_session"
        ) as mock_make_session:
            session_factory()
        mock_make_session.assert_called_once_with(redact_values=("super-secret-token",))

    def test_no_app_token_sends_no_header(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.cdc_open_data.cdc_open_data.validate_via_probe",
            return_value=(True, 200),
        ) as mock_probe:
            validate_cdc_open_data_credentials("", "9bhg-hcku")
        assert mock_probe.call_args.kwargs["headers"] is None


class TestCdcOpenDataSourceResumeBehavior:
    """End-to-end resume behaviour of ``cdc_open_data_source`` via ``rest_api_resource``."""

    def _drive(
        self,
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
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            source_response = cdc_open_data_source(
                dataset_id="9bhg-hcku",
                app_token="",
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
            )
            list(cast(Iterable[Any], source_response.items()))
            return mock_session, sent_params

    def test_full_refresh_orders_by_id_with_no_where_filter(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response([{":id": "row-1"}])]
        _, sent_params = self._drive(manager, responses)

        assert sent_params[0]["$order"] == ":id"
        assert "$where" not in sent_params[0]
        assert sent_params[0]["$$exclude_system_fields"] == "false"

    def test_incremental_sync_adds_where_filter_and_orders_by_updated_at(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response([{":id": "row-1", ":updated_at": "2024-06-02T00:00:00.000"}])]
        _, sent_params = self._drive(
            manager,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 6, 1, 0, 0, 0),
        )

        assert sent_params[0]["$order"] == ":updated_at,:id"
        assert sent_params[0]["$where"] == ":updated_at > '2024-06-01T00:00:00'"

    def test_incremental_sync_without_last_value_omits_where_filter(self) -> None:
        # First-ever incremental sync has no watermark yet, so it must not filter anything out.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response([{":id": "row-1"}])]
        _, sent_params = self._drive(manager, responses, should_use_incremental_field=True)

        assert "$where" not in sent_params[0]

    def test_fresh_run_saves_offset_after_each_non_terminal_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        full_page = [{":id": f"row-{i}"} for i in range(PAGE_SIZE)]
        responses = [
            _make_http_response(full_page),
            _make_http_response([{":id": "row-last"}]),
        ]
        _, sent_params = self._drive(manager, responses)

        offsets_sent = [p.get("$offset") for p in sent_params]
        assert offsets_sent == [0, PAGE_SIZE]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [CdcOpenDataResumeConfig(next_offset=PAGE_SIZE)]

    def test_resume_seeds_paginator_with_saved_offset(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = CdcOpenDataResumeConfig(next_offset=40_000)

        responses = [_make_http_response([{":id": "row-1"}])]
        _, sent_params = self._drive(manager, responses)

        assert sent_params[0]["$offset"] == 40_000
        manager.load_state.assert_called_once()

    def test_terminal_short_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response([{":id": "only"}])]
        self._drive(manager, responses)

        manager.save_state.assert_not_called()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response([{":id": "a"}])]
        self._drive(manager, responses)

        manager.load_state.assert_not_called()
