import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.zylo.zylo import (
    INITIAL_INCREMENTAL_VALUE,
    ZyloResumeConfig,
    _format_zylo_filter_date,
    get_resource,
    probe_endpoint_status,
    validate_credentials,
    zylo_source,
)


def _endpoint(resource: Any) -> dict[str, Any]:
    return cast(dict[str, Any], resource["endpoint"])


def _params(resource: Any) -> dict[str, Any]:
    return cast(dict[str, Any], _endpoint(resource)["params"])


class TestFormatZyloFilterDate:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02,gte"),
            (date(2024, 1, 2), "2024-01-02,gte"),
            ("2024-01-02 03:04:05", "2024-01-02,gte"),
            ("2024-01-02", "2024-01-02,gte"),
        ],
    )
    def test_formats_to_date_with_gte_suffix(self, value: Any, expected: str) -> None:
        assert _format_zylo_filter_date(value) == expected

    def test_unparseable_value_falls_back_to_raw_with_suffix(self) -> None:
        assert _format_zylo_filter_date("not-a-date") == "not-a-date,gte"


class TestGetResource:
    @pytest.mark.parametrize(
        ("endpoint", "table_name", "primary_key"),
        [
            ("Applications", "applications", ["id"]),
            ("ApplicationLicenses", "application_licenses", ["id"]),
            ("ApplicationUsers", "application_users", ["id"]),
            ("Contracts", "contracts", ["id"]),
            ("ContractLineItems", "contract_line_items", ["id"]),
            ("Payments", "payments", ["id"]),
            ("PurchaseOrders", "purchase_orders", ["id"]),
            ("POLineItems", "po_line_items", ["id"]),
            ("Suppliers", "suppliers", ["id"]),
            ("SavingsEvents", "savings_events", ["id"]),
            ("ApplicationBudgets", "application_budgets", ["application_id", "year"]),
            ("ActivityHistory", "activity_history", ["id"]),
        ],
    )
    def test_table_name_and_primary_key(self, endpoint: str, table_name: str, primary_key: list[str]) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=False, incremental_field=None)
        assert resource["table_name"] == table_name
        assert resource["primary_key"] == primary_key

    def test_full_refresh_sorts_by_default_created_field(self) -> None:
        resource = get_resource("Applications", should_use_incremental_field=False, incremental_field=None)
        params = _params(resource)
        assert params["sort"] == "+zylo_created_at"
        assert resource["write_disposition"] == "replace"
        assert set(params.keys()) == {"sort"}

    def test_incremental_endpoint_uses_selected_cursor(self) -> None:
        resource = get_resource("Contracts", should_use_incremental_field=True, incremental_field="zylo_modified_at")
        params = _params(resource)
        assert params["sort"] == "+zylo_modified_at"
        gte = cast(dict[str, Any], params["zylo_modified_at"])
        assert gte["type"] == "incremental"
        assert gte["cursor_path"] == "zylo_modified_at"
        assert gte["initial_value"] == INITIAL_INCREMENTAL_VALUE
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}

    @pytest.mark.parametrize("incremental_field", [None, "bogus_field"])
    def test_incremental_falls_back_to_first_advertised_cursor(self, incremental_field: str | None) -> None:
        resource = get_resource("Applications", should_use_incremental_field=True, incremental_field=incremental_field)
        params = _params(resource)
        assert params["sort"] == "+zylo_created_at"
        assert "zylo_created_at" in params

    def test_incremental_disabled_when_not_requested(self) -> None:
        resource = get_resource("Applications", should_use_incremental_field=False, incremental_field="zylo_created_at")
        assert resource["write_disposition"] == "replace"
        params = _params(resource)
        assert "zylo_created_at" not in params


class TestZyloSourcePartitioning:
    def test_partition_config(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        response = zylo_source(
            token_id="tok_id",
            token_secret="tok_secret",
            endpoint="Applications",
            team_id=1,
            job_id="job",
            resumable_source_manager=manager,
            db_incremental_field_last_value=None,
            should_use_incremental_field=False,
        )

        assert response.name == "Applications"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["zylo_created_at"]
        assert response.partition_format == "month"


def _make_http_response(body: list[dict[str, Any]], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestZyloSourceResumeBehavior:
    """End-to-end resume behaviour of ``zylo_source`` via ``rest_api_resource``."""

    def _drive(
        self,
        endpoint: str,
        manager: MagicMock,
        responses: list[Response],
        should_use_incremental_field: bool = False,
        incremental_field: str | None = None,
        db_incremental_field_last_value: Any = None,
    ) -> list[dict[str, Any]]:
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

            resource = zylo_source(
                token_id="tok_id",
                token_secret="tok_secret",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                db_incremental_field_last_value=db_incremental_field_last_value,
                should_use_incremental_field=should_use_incremental_field,
                incremental_field=incremental_field,
            )
            list(cast(Iterable[Any], resource.items()))
            return sent_params

    def test_fresh_run_saves_skip_after_each_non_terminal_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response([{"id": f"app_{i}"} for i in range(1000)]),
            _make_http_response([{"id": f"app_{i}"} for i in range(1000, 2000)]),
            _make_http_response([{"id": "app_last"}]),
        ]
        sent_params = self._drive("Applications", manager, responses)

        assert [p.get("skip") for p in sent_params] == [0, 1000, 2000]
        assert all(p.get("limit") == 1000 for p in sent_params)

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [ZyloResumeConfig(next_skip=1000), ZyloResumeConfig(next_skip=2000)]

    def test_resume_seeds_paginator_with_saved_skip(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = ZyloResumeConfig(next_skip=2000)

        responses = [_make_http_response([{"id": "app_last"}])]
        sent_params = self._drive("Applications", manager, responses)

        assert [p.get("skip") for p in sent_params] == [2000]
        manager.load_state.assert_called_once()

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response([{"id": "only"}])]
        self._drive("Applications", manager, responses)

        manager.save_state.assert_not_called()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response([{"id": "a"}])]
        self._drive("Applications", manager, responses)

        manager.load_state.assert_not_called()

    def test_incremental_request_carries_gte_filter_and_sort(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response([{"id": "contract_1"}])]
        sent_params = self._drive(
            "Contracts",
            manager,
            responses,
            should_use_incremental_field=True,
            incremental_field="zylo_created_at",
            db_incremental_field_last_value=None,
        )

        assert sent_params[0]["zylo_created_at"] == f"{INITIAL_INCREMENTAL_VALUE},gte"
        assert sent_params[0]["sort"] == "+zylo_created_at"

    def test_incremental_request_uses_db_last_value(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response([{"id": "contract_1"}])]
        sent_params = self._drive(
            "Contracts",
            manager,
            responses,
            should_use_incremental_field=True,
            incremental_field="zylo_modified_at",
            db_incremental_field_last_value=datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC),
        )

        assert sent_params[0]["zylo_modified_at"] == "2024-06-01,gte"


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.zylo.zylo.make_tracked_session")
    def test_status_code_mapping(self, mock_session: MagicMock, status_code: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("tok_id", "tok_secret") is expected

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.zylo.zylo.make_tracked_session")
    def test_network_error_returns_false(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("tok_id", "tok_secret") is False


class TestProbeEndpointStatus:
    @pytest.mark.parametrize("status_code", [200, 401, 403, 429, 500])
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.zylo.zylo.make_tracked_session")
    def test_returns_status_code(self, mock_session: MagicMock, status_code: int) -> None:
        response = MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert probe_endpoint_status("tok_id", "tok_secret", "/v2/purchaseOrders") == status_code

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.zylo.zylo.make_tracked_session")
    def test_network_error_returns_none(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert probe_endpoint_status("tok_id", "tok_secret", "/v2/purchaseOrders") is None
