import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.gleif.gleif import (
    GleifResumeConfig,
    _flatten_json_api_item,
    _flatten_lei_record,
    _format_gte_filter,
    gleif_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gleif.settings import LEI_ISSUERS, LEI_RECORDS

_LEI_ITEM = {
    "type": "lei-records",
    "id": "984500I2ABE9B792FF06",
    "attributes": {
        "lei": "984500I2ABE9B792FF06",
        "entity": {"legalName": {"name": "DA Digital GmbH", "language": "de"}},
        "registration": {
            "initialRegistrationDate": "2026-05-30T00:00:00Z",
            "lastUpdateDate": "2026-08-17T22:46:53Z",
        },
        "bic": None,
    },
}


class TestFlattenJsonApiItem:
    def test_merges_id_and_attributes(self) -> None:
        row = _flatten_json_api_item({"id": "abc", "attributes": {"code": "AD", "name": "Andorra"}})
        assert row == {"id": "abc", "code": "AD", "name": "Andorra"}

    @pytest.mark.parametrize("attributes", [None, "not-a-dict", []])
    def test_returns_bare_id_when_attributes_missing_or_malformed(self, attributes: Any) -> None:
        row = _flatten_json_api_item({"id": "abc", "attributes": attributes})
        assert row == {"id": "abc"}

    def test_missing_attributes_key(self) -> None:
        assert _flatten_json_api_item({"id": "abc"}) == {"id": "abc"}


class TestFlattenLeiRecord:
    def test_promotes_registration_dates_to_top_level(self) -> None:
        row = _flatten_lei_record(_LEI_ITEM)
        assert row["id"] == "984500I2ABE9B792FF06"
        assert row["initial_registration_date"] == "2026-05-30T00:00:00Z"
        assert row["last_update_date"] == "2026-08-17T22:46:53Z"
        # The nested structure is kept alongside the promoted scalars.
        assert row["registration"]["lastUpdateDate"] == "2026-08-17T22:46:53Z"

    def test_no_registration_key_does_not_add_promoted_fields(self) -> None:
        row = _flatten_lei_record({"id": "abc", "attributes": {"lei": "abc"}})
        assert "initial_registration_date" not in row
        assert "last_update_date" not in row


class TestFormatGteFilter:
    def test_prefixes_value_with_gte_operator(self) -> None:
        assert _format_gte_filter("2026-08-17T00:00:00Z") == ">=2026-08-17T00:00:00Z"


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestValidateCredentials:
    @pytest.mark.parametrize(("status_code", "expected"), [(200, True), (429, False), (500, False)])
    def test_reflects_http_status(self, status_code: int, expected: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.gleif.gleif.make_tracked_session"
        ) as mock_make_session:
            mock_make_session.return_value.get.return_value = _make_http_response({}, status_code=status_code)
            assert validate_credentials() is expected


class TestGleifSourceResumeBehavior:
    # Drives `gleif_source` with a mocked HTTP session. Returns (rows, sent_requests), where
    # sent_requests is one entry per HTTP call with the request's url and params at send time.
    def _drive(
        self,
        endpoint: str,
        manager: MagicMock,
        responses: list[Response],
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        sent_requests: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_requests.append({"url": request.url, "params": dict(request.params or {})})
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as mock_session_factory:
            mock_session = mock_session_factory.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            response = gleif_source(
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
            )
            pages = list(cast(Iterable[Any], response.items()))
            rows = [row for page in pages for row in page]
            return rows, sent_requests

    def test_lei_records_fresh_run_uses_cursor_pagination(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(
                {
                    "data": [_LEI_ITEM],
                    "links": {"next": "https://api.gleif.org/api/v1/lei-records?page%5Bcursor%5D=abc"},
                }
            ),
            _make_http_response({"data": [_LEI_ITEM]}),
        ]
        rows, sent = self._drive(LEI_RECORDS, manager, responses)

        assert sent[0]["params"] == {"page[size]": 200, "page[cursor]": "*", "sort": "registration.lastUpdateDate"}
        # The second request is driven entirely by the response's `links.next` URL.
        assert sent[1]["url"] == "https://api.gleif.org/api/v1/lei-records?page%5Bcursor%5D=abc"
        assert sent[1]["params"] == {}
        assert rows[0]["last_update_date"] == "2026-08-17T22:46:53Z"

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [GleifResumeConfig(next_url="https://api.gleif.org/api/v1/lei-records?page%5Bcursor%5D=abc")]

    def test_lei_records_incremental_run_adds_gte_filter(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"data": [_LEI_ITEM]})]
        _, sent = self._drive(
            LEI_RECORDS,
            manager,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-08-17T00:00:00Z",
        )

        assert sent[0]["params"]["filter[registration.lastUpdateDate]"] == ">=2026-08-17T00:00:00Z"

    def test_lei_records_incremental_without_watermark_omits_filter(self) -> None:
        # A schema's first incremental sync has no watermark yet, so it must fetch everything.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"data": [_LEI_ITEM]})]
        _, sent = self._drive(
            LEI_RECORDS, manager, responses, should_use_incremental_field=True, db_incremental_field_last_value=None
        )

        assert "filter[registration.lastUpdateDate]" not in sent[0]["params"]

    def test_reference_table_uses_page_size_only(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"data": [{"id": "029200067A7K6CH0H586", "attributes": {"name": "CSCS"}}]})]
        rows, sent = self._drive(LEI_ISSUERS, manager, responses)

        assert sent[0]["params"] == {"page[size]": 200}
        assert rows == [{"id": "029200067A7K6CH0H586", "name": "CSCS"}]

    def test_resume_seeds_paginator_with_saved_next_url(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = GleifResumeConfig(
            next_url="https://api.gleif.org/api/v1/lei-records?page%5Bcursor%5D=resumed"
        )

        responses = [_make_http_response({"data": [_LEI_ITEM]})]
        _, sent = self._drive(LEI_RECORDS, manager, responses)

        assert sent[0]["url"] == "https://api.gleif.org/api/v1/lei-records?page%5Bcursor%5D=resumed"
        assert sent[0]["params"] == {}
        manager.load_state.assert_called_once()

    def test_terminal_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"data": [_LEI_ITEM]})]
        self._drive(LEI_RECORDS, manager, responses)

        manager.save_state.assert_not_called()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"data": [_LEI_ITEM]})]
        self._drive(LEI_RECORDS, manager, responses)

        manager.load_state.assert_not_called()

    @pytest.mark.parametrize(
        ("endpoint", "should_use_incremental_field", "expected_disposition"),
        [
            (LEI_RECORDS, True, "merge"),
            (LEI_RECORDS, False, "replace"),
            (LEI_ISSUERS, True, "replace"),  # LeiIssuers has no incremental field to key a merge on
            (LEI_ISSUERS, False, "replace"),
        ],
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.gleif.gleif.rest_api_resource")
    def test_write_disposition_follows_incremental_support(
        self,
        mock_rest_api_resource: MagicMock,
        endpoint: str,
        should_use_incremental_field: bool,
        expected_disposition: str,
    ) -> None:
        mock_result = MagicMock()
        mock_result.name = endpoint
        mock_result.column_hints = None
        mock_rest_api_resource.return_value = mock_result

        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        response = gleif_source(
            endpoint=endpoint,
            team_id=123,
            job_id="test_job",
            resumable_source_manager=manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value="2026-08-17T00:00:00Z" if should_use_incremental_field else None,
        )

        config = mock_rest_api_resource.call_args.args[0]
        write_disposition = config["resource_defaults"]["write_disposition"]
        if expected_disposition == "merge":
            assert write_disposition == {"disposition": "merge", "strategy": "upsert"}
        else:
            assert write_disposition == "replace"

        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        if endpoint == LEI_RECORDS:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["initial_registration_date"]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
