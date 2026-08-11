import json
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import TrackedHTTPAdapter
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.settings import (
    ENDPOINT_PATHS,
    INCREMENTAL_FIELDS,
    WEBHOOK_TOPICS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.woocommerce import (
    DEFAULT_PER_PAGE,
    WOOCOMMERCE_USER_AGENT,
    WooCommerceAuth,
    WooCommercePaginator,
    WooCommerceResumeConfig,
    _HostGuardedAdapter,
    _make_guarded_session,
    _to_woocommerce_datetime,
    create_webhook,
    delete_webhook,
    get_external_webhook_info,
    get_resource,
    normalize_store_url,
    validate_credentials,
    webhook_table_transformer,
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


class TestGuardedSessionUserAgent:
    def test_sets_non_default_user_agent(self) -> None:
        # Managed WordPress hosts/WAFs block the default `python-requests` agent with a 403,
        # so every request must go out under our identifiable agent instead.
        session = _make_guarded_session(team_id=123)
        assert session.headers["User-Agent"] == WOOCOMMERCE_USER_AGENT
        assert "python-requests" not in session.headers["User-Agent"]


class TestWooCommerceAuth:
    def test_sends_query_string_credentials_and_no_authorization_header(self) -> None:
        # Auth must go in the query string with no Authorization header. A Basic header trips
        # hosts running a JWT/security plugin, which reject it with a 403 before WooCommerce
        # sees the key; reintroducing the header would break those stores again.
        prepared = Request(method="GET", url="https://example.com/wp-json/wc/v3/products", params={"page": 1}).prepare()

        WooCommerceAuth("ck_test", "cs_test")(prepared)

        assert "Authorization" not in prepared.headers
        assert prepared.url is not None
        assert "consumer_key=ck_test" in prepared.url
        assert "consumer_secret=cs_test" in prepared.url
        # Existing query params are preserved, not clobbered.
        assert "page=1" in prepared.url

    def test_secret_values_redacts_both_credentials(self) -> None:
        assert set(WooCommerceAuth("ck_test", "cs_test").secret_values()) == {"ck_test", "cs_test"}


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


def _json_response(status_code: int, payload: Any) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = payload
    return response


class TestWebhookManagement:
    """`_make_guarded_session` is the network boundary; everything below it is mocked."""

    def _session(self, list_pages: list[Any], write_response: Any = None) -> MagicMock:
        session = MagicMock()
        session.get.side_effect = [_json_response(200, page) for page in list_pages]
        session.post.return_value = write_response or _json_response(201, {"id": 1})
        session.delete.return_value = _json_response(200, {"id": 1})
        return session

    def _patch(self, session: MagicMock) -> Any:
        return patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.woocommerce._make_guarded_session",
            return_value=session,
        )

    def test_create_registers_every_topic_with_one_shared_secret(self) -> None:
        # Every WooCommerce webhook subscribes to exactly one topic, and they must all carry the
        # same secret — a per-topic secret would make the hog function reject seven of eight.
        session = self._session([[]])

        with self._patch(session):
            result = create_webhook("https://example.com", "ck", "cs", 123, "https://ph.test/hook")

        assert result.success is True
        secret = result.extra_inputs["signing_secret"]
        assert secret

        posted = [call.kwargs["json"] for call in session.post.call_args_list]
        assert [payload["topic"] for payload in posted] == list(WEBHOOK_TOPICS)
        assert {payload["secret"] for payload in posted} == {secret}
        assert {payload["delivery_url"] for payload in posted} == {"https://ph.test/hook"}
        assert {payload["status"] for payload in posted} == {"active"}

    def test_create_updates_an_existing_webhook_instead_of_duplicating_it(self) -> None:
        # A retried setup (or one WooCommerce auto-disabled after five failed deliveries) must
        # re-pin the new secret on the existing hook, not leave the store with two per topic.
        existing = [{"id": 7, "topic": "order.created", "delivery_url": "https://ph.test/hook", "status": "disabled"}]
        session = self._session([existing])

        with self._patch(session):
            result = create_webhook("https://example.com", "ck", "cs", 123, "https://ph.test/hook")

        assert result.success is True
        targets = [call.args[0] for call in session.post.call_args_list]
        assert "https://example.com/wp-json/wc/v3/webhooks/7" in targets
        update = next(
            call.kwargs["json"] for call in session.post.call_args_list if call.args[0].endswith("/webhooks/7")
        )
        assert update["status"] == "active"
        assert "topic" not in update

    def test_create_rolls_back_when_one_topic_fails(self) -> None:
        # Partial registration is worse than none: setup flips every webhook-capable table to
        # webhook sync, so a table whose topic never registered would stop being polled.
        session = MagicMock()
        session.get.side_effect = [
            _json_response(200, []),
            _json_response(200, [{"id": 9, "topic": "product.created", "delivery_url": "https://ph.test/hook"}]),
        ]
        session.post.side_effect = [_json_response(201, {"id": 9}), _json_response(500, {})]
        session.delete.return_value = _json_response(200, {})

        with self._patch(session):
            result = create_webhook("https://example.com", "ck", "cs", 123, "https://ph.test/hook")

        assert result.success is False
        assert result.extra_inputs == {}
        session.delete.assert_called_once()
        assert session.delete.call_args.args[0].endswith("/webhooks/9")

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_create_reports_a_read_only_key_as_a_permission_problem(self, status_code: int) -> None:
        # Webhook management needs Read/Write; the source itself only asks for Read, so this is
        # the expected failure and the message has to say how to fix it.
        session = self._session([[]], write_response=_json_response(status_code, {}))
        session.get.side_effect = [_json_response(200, []), _json_response(200, [])]

        with self._patch(session):
            result = create_webhook("https://example.com", "ck", "cs", 123, "https://ph.test/hook")

        assert result.success is False
        assert result.error is not None
        assert "Read/Write" in result.error

    def test_list_pages_until_a_short_page(self) -> None:
        first_page = [
            {"id": index, "topic": "order.created", "delivery_url": "https://other.test/hook"}
            for index in range(DEFAULT_PER_PAGE)
        ]
        session = self._session(
            [first_page, [{"id": 999, "topic": "order.updated", "delivery_url": "https://ph.test/hook"}]]
        )

        with self._patch(session):
            info = get_external_webhook_info("https://example.com", "ck", "cs", 123, "https://ph.test/hook")

        assert session.get.call_count == 2
        # `status=all` matters: the default list hides the paused and auto-disabled hooks we
        # need to find rather than duplicate.
        assert session.get.call_args.kwargs["params"]["status"] == "all"
        assert info.exists is True
        assert info.enabled_events == ["order.updated"]

    def test_delete_only_removes_our_delivery_url_and_forces(self) -> None:
        # `force=true` is required — WooCommerce 501s on a soft delete — and a store's own
        # webhooks must survive.
        session = self._session(
            [
                [
                    {"id": 1, "topic": "order.created", "delivery_url": "https://ph.test/hook"},
                    {"id": 2, "topic": "order.created", "delivery_url": "https://someone-else.test/hook"},
                ]
            ]
        )

        with self._patch(session):
            result = delete_webhook("https://example.com", "ck", "cs", 123, "https://ph.test/hook")

        assert result.success is True
        assert session.delete.call_count == 1
        assert session.delete.call_args.args[0].endswith("/webhooks/1")
        assert session.delete.call_args.kwargs["params"] == {"force": "true"}

    def test_delete_succeeds_when_nothing_is_registered(self) -> None:
        session = self._session([[]])

        with self._patch(session):
            result = delete_webhook("https://example.com", "ck", "cs", 123, "https://ph.test/hook")

        assert result.success is True
        session.delete.assert_not_called()

    def test_info_reports_the_unhealthy_topic_not_the_first_one(self) -> None:
        # WooCommerce disables one webhook at a time after five failures, so an "active" first
        # row would hide a topic that has stopped delivering.
        session = self._session(
            [
                [
                    {"id": 1, "topic": "order.created", "delivery_url": "https://ph.test/hook", "status": "active"},
                    {"id": 2, "topic": "order.updated", "delivery_url": "https://ph.test/hook", "status": "disabled"},
                ]
            ]
        )

        with self._patch(session):
            info = get_external_webhook_info("https://example.com", "ck", "cs", 123, "https://ph.test/hook")

        assert info.exists is True
        assert info.status == "disabled"
        assert info.enabled_events == ["order.created", "order.updated"]

    def test_info_reports_absence_when_no_webhook_targets_us(self) -> None:
        session = self._session([[{"id": 1, "topic": "order.created", "delivery_url": "https://someone-else.test"}]])

        with self._patch(session):
            info = get_external_webhook_info("https://example.com", "ck", "cs", 123, "https://ph.test/hook")

        assert info.exists is False

    @pytest.mark.parametrize(
        "operation",
        [create_webhook, delete_webhook, get_external_webhook_info],
    )
    def test_unsafe_host_never_reaches_the_network(self, operation: Any) -> None:
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.woocommerce._is_host_safe",
                return_value=(False, "blocked"),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.woocommerce._make_guarded_session"
            ) as MockSession,
        ):
            result = operation("https://169.254.169.254", "ck", "cs", 123, "https://ph.test/hook")

        assert getattr(result, "success", None) is not True
        MockSession.assert_not_called()


class TestWebhookTableTransformer:
    def _row(self, row_id: int, modified: str | None, status: str) -> dict[str, Any]:
        return {"id": row_id, "date_modified_gmt": modified, "status": status}

    def test_keeps_only_the_latest_delivery_per_id(self) -> None:
        # Delta merge dedupes across syncs but not within one batch, so a `created` followed by
        # an `updated` for the same order would otherwise both reach the merge.
        table = table_from_py_list(
            [
                self._row(1, "2026-05-01T10:00:00", "pending"),
                self._row(1, "2026-05-01T12:00:00", "completed"),
                self._row(2, "2026-05-01T09:00:00", "processing"),
            ]
        )

        result = webhook_table_transformer(table).to_pylist()

        assert sorted(row["id"] for row in result) == [1, 2]
        assert next(row for row in result if row["id"] == 1)["status"] == "completed"

    def test_out_of_order_delivery_still_keeps_the_newest(self) -> None:
        table = table_from_py_list(
            [
                self._row(1, "2026-05-01T12:00:00", "completed"),
                self._row(1, "2026-05-01T10:00:00", "pending"),
            ]
        )

        result = webhook_table_transformer(table).to_pylist()

        assert [row["status"] for row in result] == ["completed"]

    def test_rows_without_a_modified_timestamp_fall_back_to_delivery_order(self) -> None:
        table = table_from_py_list([self._row(1, None, "first"), self._row(1, None, "second")])

        result = webhook_table_transformer(table).to_pylist()

        assert [row["status"] for row in result] == ["second"]

    def test_empty_batch_passes_through(self) -> None:
        table = table_from_py_list([])
        assert webhook_table_transformer(table).num_rows == 0
