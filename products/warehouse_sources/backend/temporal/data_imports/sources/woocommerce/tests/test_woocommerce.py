import json
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import TrackedHTTPAdapter
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.settings import (
    ENDPOINT_PATHS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.woocommerce import (
    DEFAULT_PER_PAGE,
    WooCommercePaginator,
    WooCommerceResumeConfig,
    _HostGuardedAdapter,
    _to_woocommerce_datetime,
    get_resource,
    normalize_store_url,
    validate_credentials,
    woocommerce_source,
)


class TestNormalizeStoreUrl:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("https://example.com", "https://example.com"),
            ("https://example.com/", "https://example.com"),
            ("http://example.com", "https://example.com"),
            ("example.com", "https://example.com"),
            ("  https://example.com/  ", "https://example.com"),
            ("https://shop.example.com/store", "https://shop.example.com/store"),
        ],
    )
    def test_normalize(self, raw: str, expected: str) -> None:
        assert normalize_store_url(raw) == expected


class TestToWooCommerceDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            ("2024-01-01T00:00:00", "2024-01-01T00:00:00"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05"),
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05"),
            (date(2024, 5, 6), "2024-05-06T00:00:00"),
        ],
    )
    def test_format(self, value: Any, expected: Any) -> None:
        assert _to_woocommerce_datetime(value) == expected

    def test_tz_aware_converted_to_utc(self) -> None:
        plus_two = timezone(timedelta(hours=2))
        value = datetime(2024, 1, 2, 12, 0, 0, tzinfo=plus_two)
        assert _to_woocommerce_datetime(value) == "2024-01-02T10:00:00"


class TestWooCommercePaginator:
    def _response(self, total_pages: int | None) -> MagicMock:
        response = MagicMock()
        response.headers = {} if total_pages is None else {"X-WP-TotalPages": str(total_pages)}
        return response

    def test_initial_state(self) -> None:
        paginator = WooCommercePaginator()
        assert paginator.page == 1
        assert paginator.per_page == DEFAULT_PER_PAGE
        assert paginator.has_next_page is True

    def test_init_request_sets_page_and_per_page(self) -> None:
        paginator = WooCommercePaginator()
        request = Request(method="GET", url="https://example.com/wp-json/wc/v3/products")
        paginator.init_request(request)
        assert request.params["page"] == 1
        assert request.params["per_page"] == DEFAULT_PER_PAGE

    def test_has_more_pages_via_header(self) -> None:
        paginator = WooCommercePaginator()
        paginator.update_state(self._response(total_pages=3), data=[{"id": 1}])
        assert paginator.has_next_page is True
        assert paginator.page == 2

    def test_stops_on_last_page_via_header(self) -> None:
        paginator = WooCommercePaginator(page=3)
        paginator.update_state(self._response(total_pages=3), data=[{"id": 1}])
        assert paginator.has_next_page is False
        assert paginator.page == 3

    def test_stops_on_empty_page(self) -> None:
        paginator = WooCommercePaginator()
        paginator.update_state(self._response(total_pages=5), data=[])
        assert paginator.has_next_page is False

    def test_fallback_continues_on_full_page_without_header(self) -> None:
        paginator = WooCommercePaginator(per_page=2)
        paginator.update_state(self._response(total_pages=None), data=[{"id": 1}, {"id": 2}])
        assert paginator.has_next_page is True
        assert paginator.page == 2

    def test_fallback_stops_on_short_page_without_header(self) -> None:
        paginator = WooCommercePaginator(per_page=2)
        paginator.update_state(self._response(total_pages=None), data=[{"id": 1}])
        assert paginator.has_next_page is False

    def test_resume_state_round_trip(self) -> None:
        paginator = WooCommercePaginator()
        paginator.update_state(self._response(total_pages=10), data=[{"id": 1}])
        assert paginator.get_resume_state() == {"page": 2}

        resumed = WooCommercePaginator()
        resumed.set_resume_state({"page": 2})
        assert resumed.page == 2
        assert resumed.has_next_page is True

    def test_resume_state_none_on_terminal_page(self) -> None:
        paginator = WooCommercePaginator(page=2)
        paginator.update_state(self._response(total_pages=2), data=[{"id": 1}])
        assert paginator.get_resume_state() is None


def _endpoint(resource: Any) -> dict[str, Any]:
    # `EndpointResource["endpoint"]` is typed `str | Endpoint | None`; in our resources it's
    # always the dict form, so cast for indexing in assertions.
    return cast(dict[str, Any], resource["endpoint"])


class TestGetResource:
    @pytest.mark.parametrize("endpoint", sorted(ENDPOINT_PATHS))
    def test_path_and_name(self, endpoint: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=False)
        assert resource["name"] == endpoint
        assert resource["table_name"] == endpoint
        assert _endpoint(resource)["path"] == ENDPOINT_PATHS[endpoint]
        assert resource["table_format"] == "delta"

    def test_full_refresh_uses_replace(self) -> None:
        resource = get_resource("customers", should_use_incremental_field=False)
        assert resource["write_disposition"] == "replace"
        assert _endpoint(resource)["params"] == {}

    @pytest.mark.parametrize("endpoint", sorted(INCREMENTAL_FIELDS))
    def test_incremental_uses_merge_and_modified_after(self, endpoint: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=True)
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}

        params = cast(dict[str, Any], _endpoint(resource)["params"])
        assert params["dates_are_gmt"] == "true"
        modified_after = cast(dict[str, Any], params["modified_after"])
        assert modified_after["type"] == "incremental"
        assert modified_after["cursor_path"] == "date_modified_gmt"

    def test_non_incremental_endpoint_stays_full_refresh_even_when_requested(self) -> None:
        # `customers` has no server-side modified filter, so incremental must not be wired up.
        resource = get_resource("customers", should_use_incremental_field=True)
        assert resource["write_disposition"] == "replace"
        assert "modified_after" not in cast(dict[str, Any], _endpoint(resource)["params"])


def _make_http_response(body: list[dict[str, Any]], total_pages: int | None = None, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    if total_pages is not None:
        resp.headers["X-WP-TotalPages"] = str(total_pages)
    return resp


class TestWooCommerceSourceResumeBehavior:
    """End-to-end resume behaviour of ``woocommerce_source`` via ``rest_api_resource``."""

    def _drive(
        self,
        endpoint: str,
        manager: MagicMock,
        responses: list[Response],
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
    ) -> list[dict[str, Any]]:
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.woocommerce._make_guarded_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            resource = woocommerce_source(
                store_url="https://example.com",
                consumer_key="ck_test",
                consumer_secret="cs_test",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                db_incremental_field_last_value=db_incremental_field_last_value,
                should_use_incremental_field=should_use_incremental_field,
            )
            list(cast(Iterable[Any], resource))
            return sent_params

    def test_fresh_run_saves_page_after_each_non_terminal_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response([{"id": 1}], total_pages=3),
            _make_http_response([{"id": 2}], total_pages=3),
            _make_http_response([{"id": 3}], total_pages=3),
        ]
        sent_params = self._drive("products", manager, responses)

        assert [p.get("page") for p in sent_params] == [1, 2, 3]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [WooCommerceResumeConfig(page=2), WooCommerceResumeConfig(page=3)]

    def test_resume_seeds_paginator_with_saved_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = WooCommerceResumeConfig(page=5)

        responses = [_make_http_response([{"id": 9}], total_pages=5)]
        sent_params = self._drive("products", manager, responses)

        assert [p.get("page") for p in sent_params] == [5]
        manager.load_state.assert_called_once()

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response([{"id": 1}], total_pages=1)]
        self._drive("products", manager, responses)

        manager.save_state.assert_not_called()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response([{"id": 1}], total_pages=1)]
        self._drive("products", manager, responses)

        manager.load_state.assert_not_called()

    def test_incremental_injects_modified_after_filter(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response([{"id": 1}], total_pages=1)]
        sent_params = self._drive(
            "orders",
            manager,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC),
        )

        first = sent_params[0]
        assert first["modified_after"] == "2024-01-02T03:04:05"
        assert first["dates_are_gmt"] == "true"
        assert first["page"] == 1
        assert first["per_page"] == DEFAULT_PER_PAGE


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code", [200, 401, 403, 404])
    def test_returns_status_code(self, status_code: int) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.woocommerce._make_guarded_session"
        ) as MockSession:
            MockSession.return_value.get.return_value = MagicMock(status_code=status_code)
            assert validate_credentials("https://example.com", "ck", "cs", 123) == status_code

    def test_returns_none_on_connection_error(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.woocommerce._make_guarded_session"
        ) as MockSession:
            MockSession.return_value.get.side_effect = Exception("boom")
            assert validate_credentials("https://example.com", "ck", "cs", 123) is None

    def test_unsafe_host_short_circuits_without_request(self) -> None:
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.woocommerce._is_host_safe",
                return_value=(False, "blocked"),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.woocommerce._make_guarded_session"
            ) as MockSession,
        ):
            assert validate_credentials("https://169.254.169.254", "ck", "cs", 123) is None
            MockSession.return_value.get.assert_not_called()


class TestHostGuardedAdapter:
    def _prepared(self, url: str) -> Any:
        request = MagicMock()
        request.url = url
        return request

    def test_blocks_redirect_to_internal_host(self) -> None:
        adapter = _HostGuardedAdapter(team_id=123)
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.woocommerce._is_host_safe",
            return_value=(False, "Hosts with internal IP addresses are not allowed"),
        ):
            # `requests` calls `send` again for the redirect hop, so a 30x toward an
            # internal address is caught here even though the original host was safe.
            with pytest.raises(ValueError, match="internal IP"):
                adapter.send(self._prepared("https://169.254.169.254/wp-json/wc/v3/products"))

    def test_allows_safe_host_and_delegates(self) -> None:
        adapter = _HostGuardedAdapter(team_id=123)
        sentinel = MagicMock()
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.woocommerce._is_host_safe",
                return_value=(True, None),
            ),
            patch.object(TrackedHTTPAdapter, "send", return_value=sentinel) as mock_super_send,
        ):
            result = adapter.send(self._prepared("https://example.com/wp-json/wc/v3/products"))

        assert result is sentinel
        mock_super_send.assert_called_once()


class TestSourceHostGuard:
    def test_woocommerce_source_rejects_unsafe_host(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.woocommerce._is_host_safe",
            return_value=(False, "Hosts with internal IP addresses are not allowed"),
        ):
            with pytest.raises(ValueError, match="internal IP"):
                woocommerce_source(
                    store_url="https://169.254.169.254",
                    consumer_key="ck",
                    consumer_secret="cs",
                    endpoint="products",
                    team_id=123,
                    job_id="job",
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=None,
                )
