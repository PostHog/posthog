import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.webflow.settings import (
    ALL_WEBHOOK_EVENTS,
    WEBFLOW_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.webflow.webflow import (
    WebflowResumeConfig,
    _extract_items,
    _resolve_collection_id,
    create_webhook,
    delete_webhook,
    get_external_webhook_info,
    validate_credentials,
    webflow_source,
    webhook_table_transformer,
)

# The sync transport builds its session via make_tracked_session inside the shared rest_client.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials / list_collections build their own tracked session in the webflow module.
WEBFLOW_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.webflow.webflow.make_tracked_session"
)


def _make_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _make_manager(resume_state: WebflowResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: MagicMock, responses: list[Response]) -> tuple[list[str], list[dict[str, Any]]]:
    """Wire a mock session; return (urls, params) snapshotted AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy
    when each request is prepared rather than reading the final state after the run.
    """
    session.headers = {}
    urls: list[str] = []
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> MagicMock:
        urls.append(request.url)
        param_snapshots.append(dict(request.params or {}))
        return MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return urls, param_snapshots


def _drive(
    manager: MagicMock, responses: list[Response], schema_name: str = "pages"
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    with patch(CLIENT_SESSION_PATCH) as MockSession:
        session = MockSession.return_value
        urls, params = _wire(session, responses)
        response = webflow_source(
            api_token="token",
            site_id="site-1",
            schema_name=schema_name,
            team_id=1,
            job_id="j",
            resumable_source_manager=manager,
        )
        rows = [row for page in cast("Iterable[Any]", response.items()) for row in page]
    return rows, urls, params


class TestExtractItems:
    @parameterized.expand(
        [
            ("configured_key", {"items": [{"id": 1}]}, "items", [{"id": 1}]),
            ("named_envelope", {"sites": [{"id": 1}]}, "sites", [{"id": 1}]),
            ("bare_list", [{"id": 1}], "items", [{"id": 1}]),
            ("missing_key_fallback", {"weird": [{"id": 7}], "pagination": {}}, "items", [{"id": 7}]),
            ("pagination_skipped", {"pagination": [1, 2], "orders": [{"id": 9}]}, "orders", [{"id": 9}]),
            ("nothing", {"pagination": {}}, "items", []),
            ("not_a_dict", 5, "items", []),
        ]
    )
    def test_extract_items(self, _name: str, data: Any, data_key: str, expected: list[dict[str, Any]]) -> None:
        assert _extract_items(data, data_key) == expected


class TestGetRows:
    def test_fresh_run_paginates_until_total_and_saves_after_each_page(self) -> None:
        manager = _make_manager()
        # Full pages until the grand total (pagination.total) is reached; offset advances by page size.
        page1 = [{"id": f"a{i}"} for i in range(100)]
        page2 = [{"id": f"b{i}"} for i in range(100)]
        page3 = [{"id": f"c{i}"} for i in range(50)]
        responses = [
            _make_response({"pages": page1, "pagination": {"total": 250, "offset": 0}}),
            _make_response({"pages": page2, "pagination": {"total": 250, "offset": 100}}),
            _make_response({"pages": page3, "pagination": {"total": 250, "offset": 200}}),
        ]
        rows, _urls, params = _drive(manager, responses)

        assert len(rows) == 250
        assert [p["offset"] for p in params] == [0, 100, 200]
        assert [p["limit"] for p in params] == [100, 100, 100]
        # A checkpoint (pointing at the next page) is saved after each non-terminal page; the
        # final page terminates via total and saves nothing.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [WebflowResumeConfig(offset=100), WebflowResumeConfig(offset=200)]

    def test_resume_starts_from_saved_offset(self) -> None:
        manager = _make_manager(WebflowResumeConfig(offset=200))
        responses = [_make_response({"pages": [{"id": "c"}], "pagination": {"total": 250, "offset": 200}})]

        rows, _urls, params = _drive(manager, responses)

        assert rows == [{"id": "c"}]
        assert params[0]["offset"] == 200
        manager.load_state.assert_called_once()

    def test_terminates_on_short_page(self) -> None:
        manager = _make_manager()
        responses = [_make_response({"pages": [{"id": "only"}]})]

        rows, _urls, _params = _drive(manager, responses)

        assert rows == [{"id": "only"}]
        manager.save_state.assert_not_called()

    def test_single_object_endpoint_wraps_one_row_and_fetches_once(self) -> None:
        manager = _make_manager()
        # /sites/{site_id} returns a single site object, not a list envelope.
        responses = [_make_response({"id": "s1", "displayName": "My site"})]

        rows, urls, params = _drive(manager, responses, schema_name="sites")

        assert rows == [{"id": "s1", "displayName": "My site"}]
        assert urls == ["https://api.webflow.com/v2/sites/site-1"]
        # Not paginated: no offset/limit params are injected.
        assert "offset" not in params[0]
        manager.save_state.assert_not_called()

    def test_products_endpoint_flattens_nested_product(self) -> None:
        manager = _make_manager()
        responses = [
            _make_response(
                {
                    "items": [
                        {"product": {"id": "p1", "createdOn": "2026-01-01"}, "skus": [{"id": "s1"}]},
                    ]
                }
            )
        ]

        rows, _urls, _params = _drive(manager, responses, schema_name="products")

        assert rows == [{"id": "p1", "createdOn": "2026-01-01", "skus": [{"id": "s1"}]}]

    def test_collection_items_request_includes_stable_sort(self) -> None:
        manager = _make_manager()
        responses = [_make_response({"items": [{"id": "i1"}]})]
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.webflow.webflow._resolve_collection_id",
            return_value="col-99",
        ):
            rows, urls, params = _drive(manager, responses, schema_name="collection_blog")

        assert rows == [{"id": "i1"}]
        assert urls[0] == "https://api.webflow.com/v2/collections/col-99/items"
        assert params[0]["sortBy"] == "createdOn"
        assert params[0]["sortOrder"] == "asc"

    def test_site_id_with_path_delimiters_is_encoded_into_a_single_segment(self) -> None:
        # A site_id containing path/query delimiters must not redirect the request to an
        # account-level (or otherwise unintended) Webflow endpoint.
        manager = _make_manager()
        responses = [_make_response({"pages": [{"id": "a"}]})]
        with patch(CLIENT_SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            urls, _params = _wire(session, responses)
            response = webflow_source(
                api_token="token",
                site_id="../../sites",
                schema_name="pages",
                team_id=1,
                job_id="j",
                resumable_source_manager=manager,
            )
            list(cast("Iterable[Any]", response.items()))

        assert urls[0] == "https://api.webflow.com/v2/sites/..%2F..%2Fsites/pages"

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = _make_manager()
        responses = [_make_response({"pages": [{"id": "a"}]})]

        _drive(manager, responses)

        manager.load_state.assert_not_called()


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("bad_token", 401, None, False),
            ("missing_scope_at_create", 403, None, True),
            ("missing_scope_for_schema", 403, "products", False),
            ("invalid_site_id", 400, None, False),
            ("site_not_found", 404, None, False),
            ("server_error", 500, None, False),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, schema_name: str | None, expected_ok: bool) -> None:
        with patch(WEBFLOW_SESSION_PATCH) as MockSession:
            MockSession.return_value.get.return_value = _make_response({"message": "nope"}, status_code=status_code)
            ok, _error = validate_credentials("token", "site-1", schema_name)
        assert ok is expected_ok

    def test_invalid_site_id_400_does_not_leak_raw_envelope(self) -> None:
        # A malformed Site ID gets a 400 with Webflow's raw "Validation Error: ..." envelope, which
        # must not surface to the user.
        with patch(WEBFLOW_SESSION_PATCH) as MockSession:
            MockSession.return_value.get.return_value = _make_response(
                {"message": "Validation Error: Provided IDs are invalid: Site ID"}, status_code=400
            )
            ok, error = validate_credentials("token", "site-1")
        assert ok is False
        assert "Site ID isn't valid" in (error or "")
        assert "Validation Error" not in (error or "")

    def test_request_exception_returns_error(self) -> None:
        with patch(WEBFLOW_SESSION_PATCH) as MockSession:
            MockSession.return_value.get.side_effect = requests.exceptions.ConnectionError("boom")
            ok, error = validate_credentials("token", "site-1")
        assert ok is False
        assert error == "boom"


class TestResolveCollectionId:
    def test_resolves_by_slug(self) -> None:
        with patch(WEBFLOW_SESSION_PATCH) as MockSession:
            MockSession.return_value.get.return_value = _make_response(
                {"collections": [{"id": "c1", "slug": "blog"}, {"id": "c2", "slug": "authors"}]}
            )
            assert _resolve_collection_id("token", "site-1", "collection_authors") == "c2"

    def test_raises_when_collection_missing(self) -> None:
        with patch(WEBFLOW_SESSION_PATCH) as MockSession:
            MockSession.return_value.get.return_value = _make_response({"collections": [{"id": "c1", "slug": "blog"}]})
            with pytest.raises(ValueError):
                _resolve_collection_id("token", "site-1", "collection_missing")


class TestWebflowSource:
    @parameterized.expand(
        [
            ("pages", "pages", ["id"]),
            ("orders", "orders", ["orderId"]),
            ("products", "products", ["id"]),
        ]
    )
    def test_source_response_primary_keys(self, _name: str, schema_name: str, expected_pks: list[str]) -> None:
        manager = _make_manager()
        with patch(CLIENT_SESSION_PATCH):
            response = webflow_source(
                "token", "site-1", schema_name, team_id=1, job_id="j", resumable_source_manager=manager
            )
        assert response.name == schema_name
        assert response.primary_keys == expected_pks
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [WEBFLOW_ENDPOINTS[schema_name].partition_key]

    def test_forms_endpoint_has_no_partitioning(self) -> None:
        manager = _make_manager()
        with patch(CLIENT_SESSION_PATCH):
            response = webflow_source(
                "token", "site-1", "forms", team_id=1, job_id="j", resumable_source_manager=manager
            )
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_collection_schema_resolves_collection_id(self) -> None:
        manager = _make_manager()
        with (
            patch(CLIENT_SESSION_PATCH),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.webflow.webflow._resolve_collection_id",
                return_value="c1",
            ) as mock_resolve,
        ):
            response = webflow_source(
                "token", "site-1", "collection_blog", team_id=1, job_id="j", resumable_source_manager=manager
            )
        mock_resolve.assert_called_once_with("token", "site-1", "collection_blog")
        assert response.name == "collection_blog"
        assert response.primary_keys == ["id"]

    def test_items_callable_lazy(self) -> None:
        # Building the SourceResponse must not send any request; only iterating items() should.
        manager = _make_manager()
        with patch(CLIENT_SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            session.send.side_effect = AssertionError("no request should be sent while building the SourceResponse")
            response = webflow_source(
                "token", "site-1", "pages", team_id=1, job_id="j", resumable_source_manager=manager
            )
            assert callable(response.items)
            assert isinstance(response.items(), Iterable)


def _webhook_list_response(webhooks: list[dict[str, Any]]) -> Response:
    return _make_response({"webhooks": webhooks, "pagination": {"limit": 100, "offset": 0, "total": len(webhooks)}})


class TestCreateWebhook:
    def test_registers_one_webhook_per_trigger_and_keeps_every_secret(self) -> None:
        # Webflow's create endpoint takes a single triggerType and issues a separate secret per
        # registration, so losing any of them leaves that trigger's deliveries unverifiable.
        with patch(WEBFLOW_SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            session.get.return_value = _webhook_list_response([])
            session.post.side_effect = [
                _make_response({"id": "w1", "triggerType": "ecomm_new_order", "secretKey": "s1"}, 201),
                _make_response({"id": "w2", "triggerType": "ecomm_order_changed", "secretKey": "s2"}, 201),
            ]

            result = create_webhook("token", "site-1", "https://webhooks.example/dwh/1")

        assert result.success is True
        assert result.extra_inputs == {"signing_secrets": ["s1", "s2"]}
        assert result.pending_inputs == []
        assert [call.kwargs["json"]["triggerType"] for call in session.post.call_args_list] == list(ALL_WEBHOOK_EVENTS)
        assert {call.kwargs["json"]["url"] for call in session.post.call_args_list} == {
            "https://webhooks.example/dwh/1"
        }

    def test_skips_triggers_already_registered_for_our_url(self) -> None:
        # Webflow caps registrations per trigger type per site, and a duplicate would keep
        # delivering after we delete "the" webhook.
        with patch(WEBFLOW_SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            session.get.return_value = _webhook_list_response(
                [{"id": "w1", "triggerType": "ecomm_new_order", "url": "https://webhooks.example/dwh/1"}]
            )
            session.post.return_value = _make_response(
                {"id": "w2", "triggerType": "ecomm_order_changed", "secretKey": "s2"}, 201
            )

            result = create_webhook("token", "site-1", "https://webhooks.example/dwh/1")

        assert [call.kwargs["json"]["triggerType"] for call in session.post.call_args_list] == ["ecomm_order_changed"]
        assert result.success is True
        # One trigger's secret was issued before we asked, so it can't be recovered.
        assert result.pending_inputs == ["signing_secret"]

    def test_registration_without_a_secret_asks_the_user_for_one(self) -> None:
        # Site tokens predating Webflow's per-webhook secrets return no secretKey; silently
        # succeeding would leave every delivery failing the signature check.
        with patch(WEBFLOW_SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            session.get.return_value = _webhook_list_response([])
            session.post.return_value = _make_response({"id": "w1"}, 201)

            result = create_webhook("token", "site-1", "https://webhooks.example/dwh/1")

        assert result.success is True
        assert result.extra_inputs == {}
        assert result.pending_inputs == ["signing_secret"]

    @parameterized.expand([("forbidden", 403), ("bad_request", 400)])
    def test_reports_failure_when_no_registration_was_created(self, _name: str, status_code: int) -> None:
        with patch(WEBFLOW_SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            session.get.return_value = _webhook_list_response([])
            session.post.return_value = _make_response({"message": "nope"}, status_code)

            result = create_webhook("token", "site-1", "https://webhooks.example/dwh/1")

        assert result.success is False
        assert result.error is not None
        assert "sites:write" in result.error

    def test_network_failure_is_reported_not_raised(self) -> None:
        with patch(WEBFLOW_SESSION_PATCH) as MockSession:
            MockSession.return_value.get.side_effect = requests.exceptions.ConnectTimeout("boom")

            result = create_webhook("token", "site-1", "https://webhooks.example/dwh/1")

        assert result.success is False
        assert result.error is not None and "boom" in result.error


class TestDeleteWebhook:
    def test_deletes_every_registration_pointing_at_our_url_and_leaves_others(self) -> None:
        with patch(WEBFLOW_SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            session.get.return_value = _webhook_list_response(
                [
                    {"id": "w1", "triggerType": "ecomm_new_order", "url": "https://webhooks.example/dwh/1"},
                    {"id": "w2", "triggerType": "ecomm_order_changed", "url": "https://webhooks.example/dwh/1"},
                    {"id": "other", "triggerType": "form_submission", "url": "https://someone-else.example"},
                ]
            )
            # A registration removed in Webflow between listing and deleting is already the
            # outcome we wanted, so a 404 must not fail the teardown.
            session.delete.side_effect = [_make_response({}, 204), _make_response({}, 404)]

            result = delete_webhook("token", "site-1", "https://webhooks.example/dwh/1")

        assert result.success is True
        deleted_ids = [call.args[0].rsplit("/", 1)[-1] for call in session.delete.call_args_list]
        assert deleted_ids == ["w1", "w2"]

    def test_reports_a_registration_webflow_refused_to_delete(self) -> None:
        with patch(WEBFLOW_SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            session.get.return_value = _webhook_list_response(
                [{"id": "w1", "triggerType": "ecomm_new_order", "url": "https://webhooks.example/dwh/1"}]
            )
            session.delete.return_value = _make_response({}, 403)

            result = delete_webhook("token", "site-1", "https://webhooks.example/dwh/1")

        assert result.success is False
        assert result.error is not None and "w1" in result.error


class TestGetExternalWebhookInfo:
    def test_reports_the_triggers_currently_registered(self) -> None:
        with patch(WEBFLOW_SESSION_PATCH) as MockSession:
            MockSession.return_value.get.return_value = _webhook_list_response(
                [
                    {
                        "id": "w1",
                        "triggerType": "ecomm_new_order",
                        "url": "https://webhooks.example/dwh/1",
                        "createdOn": "2026-01-02T00:00:00Z",
                    },
                    {
                        "id": "w2",
                        "triggerType": "ecomm_order_changed",
                        "url": "https://webhooks.example/dwh/1",
                        "createdOn": "2026-01-01T00:00:00Z",
                    },
                ]
            )

            info = get_external_webhook_info("token", "site-1", "https://webhooks.example/dwh/1")

        assert info.exists is True
        # The set drives the "missing events" hint in the UI, so a partial registration has to
        # report only what is really there.
        assert info.enabled_events == ["ecomm_new_order", "ecomm_order_changed"]
        assert info.created_at == "2026-01-01T00:00:00Z"

    def test_reports_absence_when_only_other_webhooks_exist(self) -> None:
        with patch(WEBFLOW_SESSION_PATCH) as MockSession:
            MockSession.return_value.get.return_value = _webhook_list_response(
                [{"id": "w1", "triggerType": "form_submission", "url": "https://someone-else.example"}]
            )

            info = get_external_webhook_info("token", "site-1", "https://webhooks.example/dwh/1")

        assert info.exists is False

    def test_lookup_failure_is_reported_not_raised(self) -> None:
        with patch(WEBFLOW_SESSION_PATCH) as MockSession:
            MockSession.return_value.get.return_value = _make_response({"message": "nope"}, 401)

            info = get_external_webhook_info("token", "site-1", "https://webhooks.example/dwh/1")

        assert info.exists is False
        assert info.error is not None


class TestWebhookTableTransformer:
    def _table(self, rows: list[dict[str, Any]]) -> Any:
        return table_from_py_list(rows)

    def test_keeps_only_the_latest_delivery_per_order(self) -> None:
        # Delta merge dedupes across syncs but not within a batch, so a created-then-changed
        # pair for one order would otherwise land as two rows racing on the same primary key.
        table = self._table(
            [
                {
                    "triggerType": "ecomm_new_order",
                    "webflowTimestamp": "1700000000000",
                    "payload": {"orderId": "abc123", "status": "unfulfilled"},
                },
                {
                    "triggerType": "ecomm_order_changed",
                    "webflowTimestamp": "1700000060000",
                    "payload": {"orderId": "abc123", "status": "fulfilled"},
                },
                {
                    "triggerType": "ecomm_new_order",
                    "webflowTimestamp": "1700000030000",
                    "payload": {"orderId": "def456", "status": "unfulfilled"},
                },
            ]
        )

        rows = webhook_table_transformer(table).to_pylist()

        assert sorted(rows, key=lambda r: r["orderId"]) == [
            {"orderId": "abc123", "status": "fulfilled"},
            {"orderId": "def456", "status": "unfulfilled"},
        ]

    def test_out_of_order_delivery_does_not_resurrect_the_older_row(self) -> None:
        # Webflow retries failed deliveries, so a stale event can arrive after a newer one.
        table = self._table(
            [
                {
                    "triggerType": "ecomm_order_changed",
                    "webflowTimestamp": "1700000060000",
                    "payload": {"orderId": "abc123", "status": "fulfilled"},
                },
                {
                    "triggerType": "ecomm_new_order",
                    "webflowTimestamp": "1700000000000",
                    "payload": {"orderId": "abc123", "status": "unfulfilled"},
                },
            ]
        )

        assert webhook_table_transformer(table).to_pylist() == [{"orderId": "abc123", "status": "fulfilled"}]

    def test_equal_timestamps_fall_back_to_arrival_order(self) -> None:
        table = self._table(
            [
                {
                    "triggerType": "ecomm_new_order",
                    "webflowTimestamp": "1700000000000",
                    "payload": {"orderId": "abc123", "status": "unfulfilled"},
                },
                {
                    "triggerType": "ecomm_order_changed",
                    "webflowTimestamp": "1700000000000",
                    "payload": {"orderId": "abc123", "status": "fulfilled"},
                },
            ]
        )

        assert webhook_table_transformer(table).to_pylist() == [{"orderId": "abc123", "status": "fulfilled"}]

    def test_rows_without_an_order_id_are_dropped(self) -> None:
        # A row with no primary key can't be merged; keeping it would fail the whole batch.
        table = self._table(
            [
                {"triggerType": "ecomm_new_order", "webflowTimestamp": "1700000000000", "payload": {"status": "x"}},
                {
                    "triggerType": "ecomm_new_order",
                    "webflowTimestamp": "1700000000000",
                    "payload": {"orderId": "abc123", "status": "unfulfilled"},
                },
            ]
        )

        assert webhook_table_transformer(table).to_pylist() == [{"orderId": "abc123", "status": "unfulfilled"}]

    def test_table_without_a_payload_column_yields_no_rows(self) -> None:
        assert webhook_table_transformer(self._table([{"triggerType": "site_publish"}])).num_rows == 0


class TestWebhookBackedSource:
    def test_orders_reads_from_the_webhook_manager_once_webhooks_are_live(self) -> None:
        manager = _make_manager()
        webhook_manager = MagicMock(spec=WebhookSourceManager)
        webhook_manager.webhook_enabled = AsyncMock(return_value=True)
        webhook_manager.get_items.return_value = "webhook-items"

        with patch(CLIENT_SESSION_PATCH) as MockSession:
            MockSession.return_value.send.side_effect = AssertionError("the pull API must not be hit")
            response = webflow_source(
                "token",
                "site-1",
                "orders",
                team_id=1,
                job_id="j",
                resumable_source_manager=manager,
                webhook_source_manager=webhook_manager,
            )
            assert response.items() == "webhook-items"

        webhook_manager.get_items.assert_called_once_with(table_transformer=webhook_table_transformer)
        # The polled table's identity must not change when rows arrive by webhook, or pushed
        # rows land in a different Delta table than the backfill.
        assert response.primary_keys == ["orderId"]
        assert response.partition_keys == ["acceptedOn"]

    @parameterized.expand([("pages",), ("collection_blog",)])
    def test_schema_without_webhook_support_never_consults_the_webhook_manager(self, schema_name: str) -> None:
        # Only `orders` has a Webflow trigger whose payload matches the polled table, so any
        # other schema must keep polling even when a webhook is registered on the source.
        manager = _make_manager()
        webhook_manager = MagicMock(spec=WebhookSourceManager)
        webhook_manager.webhook_enabled = AsyncMock(return_value=True)

        with (
            patch(CLIENT_SESSION_PATCH),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.webflow.webflow._resolve_collection_id",
                return_value="c1",
            ),
        ):
            webflow_source(
                "token",
                "site-1",
                schema_name,
                team_id=1,
                job_id="j",
                resumable_source_manager=manager,
                webhook_source_manager=webhook_manager,
            )

        webhook_manager.webhook_enabled.assert_not_called()
        webhook_manager.get_items.assert_not_called()
