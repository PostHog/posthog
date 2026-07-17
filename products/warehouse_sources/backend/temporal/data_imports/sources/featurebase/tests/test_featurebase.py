from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.featurebase import featurebase
from products.warehouse_sources.backend.temporal.data_imports.sources.featurebase.featurebase import (
    FeaturebaseResumeConfig,
    _build_initial_params,
    _page_predates_cutoff,
    _webhook_table_transformer,
    create_webhook,
    delete_webhook,
    featurebase_source,
    get_external_webhook_info,
    get_rows,
    sync_webhook_events,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.featurebase.settings import FEATUREBASE_ENDPOINTS

BASE = "https://do.featurebase.app/v2"


class _FakeResumableManager:
    def __init__(self, state: FeaturebaseResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[FeaturebaseResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> FeaturebaseResumeConfig | None:
        return self._state

    def save_state(self, data: FeaturebaseResumeConfig) -> None:
        self.saved.append(data)


def _response_with_status(status_code: int) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    return response


def _collect_rows(
    monkeypatch: Any,
    endpoint: str,
    pages: dict[str, Any],
    manager: _FakeResumableManager | None = None,
    fetched_urls: list[str] | None = None,
    **incremental: Any,
) -> list[dict]:
    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> Any:
        if fetched_urls is not None:
            fetched_urls.append(url)
        result = pages[url]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(featurebase, "_fetch_page", fake_fetch)
    monkeypatch.setattr(featurebase, "make_tracked_session", MagicMock())

    rows: list[dict] = []
    for batch in get_rows(
        api_key="fb_test",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager or _FakeResumableManager(),  # type: ignore[arg-type]
        **incremental,
    ):
        rows.extend(batch)
    return rows


class TestBuildInitialParams:
    @parameterized.expand(
        [
            (
                "posts_full_refresh_sorts_ascending_by_created",
                "posts",
                False,
                None,
                {"limit": 100, "sortBy": "createdAt", "sortOrder": "asc"},
            ),
            (
                "posts_incremental_updated_sweeps_recent_desc",
                "posts",
                True,
                "updatedAt",
                {"limit": 100, "sortBy": "recent", "sortOrder": "desc"},
            ),
            (
                "posts_incremental_created_sweeps_created_desc",
                "posts",
                True,
                "createdAt",
                {"limit": 100, "sortBy": "createdAt", "sortOrder": "desc"},
            ),
            (
                "comments_incremental_uses_new_sort_enum",
                "comments",
                True,
                "createdAt",
                {"limit": 100, "sortBy": "new", "privacy": "all"},
            ),
            (
                "comments_full_refresh_uses_old_sort_enum",
                "comments",
                False,
                None,
                {"limit": 100, "sortBy": "old", "privacy": "all"},
            ),
            (
                "boards_has_no_pagination_params",
                "boards",
                False,
                None,
                {},
            ),
        ]
    )
    def test_build_initial_params(
        self, _name: str, endpoint: str, incremental: bool, field: str | None, expected: dict
    ) -> None:
        params = _build_initial_params(
            FEATUREBASE_ENDPOINTS[endpoint],
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=None,
            incremental_field=field,
        )
        assert params == expected

    def test_changelogs_incremental_sends_server_side_start_date(self) -> None:
        params = _build_initial_params(
            FEATUREBASE_ENDPOINTS["changelogs"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="date",
        )
        assert params["startDate"] == "2026-03-04T02:58:14.000Z"
        assert params["sortBy"] == "date"
        assert params["sortOrder"] == "asc"

    def test_changelogs_first_incremental_sync_has_no_start_date(self) -> None:
        params = _build_initial_params(
            FEATUREBASE_ENDPOINTS["changelogs"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="date",
        )
        assert "startDate" not in params


class TestPagePredatesCutoff:
    _cutoff = datetime(2026, 1, 10, tzinfo=UTC)

    @parameterized.expand(
        [
            (
                "whole_page_older_stops_the_sweep",
                [{"createdAt": "2026-01-05T00:00:00.000Z"}, {"createdAt": "2026-01-01T00:00:00.000Z"}],
                True,
            ),
            (
                "page_with_newer_row_keeps_sweeping",
                [{"createdAt": "2026-01-15T00:00:00.000Z"}, {"createdAt": "2026-01-01T00:00:00.000Z"}],
                False,
            ),
            (
                "unparseable_field_degrades_to_full_sweep",
                [{"createdAt": None}, {"createdAt": "2026-01-01T00:00:00.000Z"}],
                False,
            ),
            ("empty_page_never_stops", [], False),
        ]
    )
    def test_page_predates_cutoff(self, _name: str, items: list[dict], expected: bool) -> None:
        assert _page_predates_cutoff(items, "createdAt", self._cutoff) is expected

    def test_no_watermark_never_stops(self) -> None:
        assert _page_predates_cutoff([{"createdAt": "2020-01-01T00:00:00.000Z"}], "createdAt", None) is False


class TestFetchPageRetries:
    def test_429_is_retried_until_success(self) -> None:
        throttled = MagicMock(status_code=429)
        good = MagicMock(status_code=200, ok=True)
        good.json.return_value = {"data": []}
        session = MagicMock()
        session.get.side_effect = [throttled, good]

        with patch.object(featurebase._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = featurebase._fetch_page(session, f"{BASE}/posts", {}, MagicMock())

        assert result == {"data": []}
        assert session.get.call_count == 2

    def test_auth_error_is_not_retried(self) -> None:
        forbidden = MagicMock(status_code=403, ok=False, text='{"success":false,"message":"Invalid API Key"}')
        forbidden.raise_for_status.side_effect = requests.HTTPError(response=_response_with_status(403))
        session = MagicMock()
        session.get.return_value = forbidden

        with patch.object(featurebase._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(requests.HTTPError):
                featurebase._fetch_page(session, f"{BASE}/posts", {}, MagicMock())

        assert session.get.call_count == 1


class TestCursorPagination:
    def test_follows_next_cursor_and_saves_state_after_yield(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            f"{BASE}/companies?limit=100": {"data": [{"id": "c1"}], "nextCursor": "cur2"},
            f"{BASE}/companies?limit=100&cursor=cur2": {"data": [{"id": "c2"}], "nextCursor": None},
        }
        rows = _collect_rows(monkeypatch, "companies", pages, manager)

        assert [r["id"] for r in rows] == ["c1", "c2"]
        # State only saved while more pages remain — a crash on the final page restarts it cleanly.
        assert [s.cursor for s in manager.saved] == ["cur2"]

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(FeaturebaseResumeConfig(cursor="cur2"))
        fetched: list[str] = []
        pages = {
            f"{BASE}/companies?limit=100&cursor=cur2": {"data": [{"id": "c2"}], "nextCursor": None},
        }
        rows = _collect_rows(monkeypatch, "companies", pages, manager, fetched_urls=fetched)

        assert [r["id"] for r in rows] == ["c2"]
        assert fetched == [f"{BASE}/companies?limit=100&cursor=cur2"]

    def test_bare_array_endpoint_yields_single_batch(self, monkeypatch: Any) -> None:
        pages = {f"{BASE}/boards": [{"id": "b1", "object": "board"}]}
        rows = _collect_rows(monkeypatch, "boards", pages)
        assert rows == [{"id": "b1", "object": "board"}]


class TestDescCutoffIncremental:
    def test_sweep_stops_once_page_predates_watermark(self, monkeypatch: Any) -> None:
        # Page 3 must never be fetched: page 2 is entirely older than the watermark, and a
        # newest-first sweep that keeps walking would re-fetch full history every sync.
        fetched: list[str] = []
        pages = {
            f"{BASE}/posts?limit=100&sortBy=recent&sortOrder=desc": {
                "data": [{"id": "p1", "updatedAt": "2026-01-15T00:00:00.000Z"}],
                "nextCursor": "cur2",
            },
            f"{BASE}/posts?limit=100&sortBy=recent&sortOrder=desc&cursor=cur2": {
                "data": [{"id": "p2", "updatedAt": "2026-01-05T00:00:00.000Z"}],
                "nextCursor": "cur3",
            },
        }
        rows = _collect_rows(
            monkeypatch,
            "posts",
            pages,
            fetched_urls=fetched,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 10, tzinfo=UTC),
            incremental_field="updatedAt",
        )

        # The boundary page is still yielded (merge dedupes re-pulled rows on the primary key).
        assert [r["id"] for r in rows] == ["p1", "p2"]
        assert len(fetched) == 2

    def test_first_incremental_sync_walks_everything(self, monkeypatch: Any) -> None:
        fetched: list[str] = []
        pages = {
            f"{BASE}/posts?limit=100&sortBy=recent&sortOrder=desc": {
                "data": [{"id": "p1", "updatedAt": "2026-01-15T00:00:00.000Z"}],
                "nextCursor": "cur2",
            },
            f"{BASE}/posts?limit=100&sortBy=recent&sortOrder=desc&cursor=cur2": {
                "data": [{"id": "p2", "updatedAt": "2026-01-05T00:00:00.000Z"}],
                "nextCursor": None,
            },
        }
        rows = _collect_rows(
            monkeypatch,
            "posts",
            pages,
            fetched_urls=fetched,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="updatedAt",
        )
        assert [r["id"] for r in rows] == ["p1", "p2"]
        assert len(fetched) == 2


class TestPostVotersFanOut:
    _posts_url = f"{BASE}/posts?limit=100&sortBy=createdAt&sortOrder=asc"

    def test_config_is_opt_in_fan_out_with_composite_pk(self) -> None:
        config = FEATUREBASE_ENDPOINTS["post_voters"]
        assert config.fan_out_over_posts is True
        assert config.should_sync_default is False
        assert config.primary_keys == ["postId", "id"]

    def test_fans_out_over_every_post_injecting_post_id(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            self._posts_url: {"data": [{"id": "P1"}, {"id": "P2"}], "nextCursor": None},
            f"{BASE}/posts/P1/voters?limit=100": {
                "data": [{"id": "U1", "object": "contact"}],
                "nextCursor": None,
            },
            f"{BASE}/posts/P2/voters?limit=100": {
                "data": [{"id": "U1", "object": "contact"}, {"id": "U2", "object": "contact"}],
                "nextCursor": None,
            },
        }
        rows = _collect_rows(monkeypatch, "post_voters", pages, manager)

        assert [(r["postId"], r["id"]) for r in rows] == [("P1", "U1"), ("P2", "U1"), ("P2", "U2")]
        # Bookmark advanced to P2 so a crash between posts resumes there, not from scratch.
        assert [(s.post_id, s.cursor) for s in manager.saved] == [("P2", None)]

    def test_deleted_post_404_is_skipped(self, monkeypatch: Any) -> None:
        not_found = requests.HTTPError(response=_response_with_status(404))
        pages = {
            self._posts_url: {"data": [{"id": "P1"}, {"id": "P2"}], "nextCursor": None},
            f"{BASE}/posts/P1/voters?limit=100": not_found,
            f"{BASE}/posts/P2/voters?limit=100": {"data": [{"id": "U2"}], "nextCursor": None},
        }
        rows = _collect_rows(monkeypatch, "post_voters", pages)
        assert [(r["postId"], r["id"]) for r in rows] == [("P2", "U2")]

    def test_non_404_error_propagates(self, monkeypatch: Any) -> None:
        server_error = requests.HTTPError(response=_response_with_status(500))
        pages = {
            self._posts_url: {"data": [{"id": "P1"}], "nextCursor": None},
            f"{BASE}/posts/P1/voters?limit=100": server_error,
        }
        with pytest.raises(requests.HTTPError):
            _collect_rows(monkeypatch, "post_voters", pages)

    def test_resumes_from_bookmarked_post(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(FeaturebaseResumeConfig(cursor="vcur", post_id="P2"))
        fetched: list[str] = []
        pages = {
            self._posts_url: {"data": [{"id": "P1"}, {"id": "P2"}], "nextCursor": None},
            f"{BASE}/posts/P2/voters?limit=100&cursor=vcur": {"data": [{"id": "U9"}], "nextCursor": None},
        }
        rows = _collect_rows(monkeypatch, "post_voters", pages, manager, fetched_urls=fetched)

        # P1 was already synced before the crash: only the bookmarked post is re-fetched,
        # starting at its saved cursor.
        assert [(r["postId"], r["id"]) for r in rows] == [("P2", "U9")]
        assert f"{BASE}/posts/P1/voters?limit=100" not in fetched


class TestSourceResponse:
    def _source(self, endpoint: str, should_use_incremental_field: bool = False) -> Any:
        webhook_manager = MagicMock()
        webhook_manager.webhook_enabled = MagicMock(return_value=False)
        with patch.object(featurebase, "async_to_sync", lambda fn: fn):
            return featurebase_source(
                api_key="fb_test",
                endpoint=endpoint,
                logger=MagicMock(),
                resumable_source_manager=MagicMock(),
                webhook_source_manager=webhook_manager,
                should_use_incremental_field=should_use_incremental_field,
            )

    @parameterized.expand(
        [
            # Incremental desc sweeps must defer watermark persistence to job end; per-batch
            # "asc" persistence on a newest-first stream would checkpoint ≈now after batch one.
            ("posts_incremental", "posts", True, "desc"),
            ("posts_full_refresh", "posts", False, "asc"),
            ("changelogs_incremental_stays_asc", "changelogs", True, "asc"),
            ("boards_full_refresh", "boards", False, "asc"),
        ]
    )
    def test_sort_mode_matches_emit_order(self, _name: str, endpoint: str, incremental: bool, expected: str) -> None:
        assert self._source(endpoint, incremental).sort_mode == expected

    @parameterized.expand(
        [
            ("posts", ["id"], ["createdAt"]),
            ("post_voters", ["postId", "id"], None),
            ("contacts", ["id"], None),
        ]
    )
    def test_primary_and_partition_keys(
        self, endpoint: str, expected_pk: list[str], expected_partition: list[str] | None
    ) -> None:
        response = self._source(endpoint)
        assert response.primary_keys == expected_pk
        assert response.partition_keys == expected_partition


class TestWebhookTableTransformer:
    def test_keeps_only_latest_event_per_object(self) -> None:
        # post.created then post.updated for the same post in one batch: delta merge doesn't
        # dedupe within a batch, so only the newest version may survive.
        table = table_from_py_list(
            [
                {
                    "id": "notif_1",
                    "topic": "post.created",
                    "createdAt": "2026-01-01T00:00:00.000Z",
                    "data": {"item": {"id": "p1", "object": "post", "title": "old title"}},
                },
                {
                    "id": "notif_2",
                    "topic": "post.updated",
                    "createdAt": "2026-01-02T00:00:00.000Z",
                    "data": {"item": {"id": "p1", "object": "post", "title": "new title"}},
                },
                {
                    "id": "notif_3",
                    "topic": "post.created",
                    "createdAt": "2026-01-01T12:00:00.000Z",
                    "data": {"item": {"id": "p2", "object": "post", "title": "other post"}},
                },
            ]
        )
        rows = sorted(_webhook_table_transformer(table).to_pylist(), key=lambda r: r["id"])
        assert rows == [
            {"id": "p1", "object": "post", "title": "new title"},
            {"id": "p2", "object": "post", "title": "other post"},
        ]

    def test_rows_without_item_id_are_dropped(self) -> None:
        table = table_from_py_list(
            [
                {"id": "notif_1", "createdAt": "2026-01-01T00:00:00.000Z", "data": {"item": {"title": "no id"}}},
                {"id": "notif_2", "createdAt": "2026-01-01T00:00:00.000Z", "data": None},
            ]
        )
        assert _webhook_table_transformer(table).to_pylist() == []


def _session_with(**methods: Any) -> MagicMock:
    session = MagicMock()
    for name, value in methods.items():
        getattr(session, name).side_effect = value if isinstance(value, list) else [value]
    return session


def _json_response(payload: Any, status_code: int = 200) -> MagicMock:
    response = MagicMock(status_code=status_code, ok=status_code < 400)
    response.json.return_value = payload
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
    else:
        response.raise_for_status.return_value = None
    return response


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid_key", 200, {"data": []}, True),
            # Featurebase responds 403 (not 401) for both missing and invalid keys.
            ("invalid_key", 403, {"success": False, "message": "Invalid API Key"}, False),
        ]
    )
    def test_validate_credentials(self, _name: str, status: int, payload: dict, expected_valid: bool) -> None:
        session = _session_with(get=_json_response(payload, status))
        with patch.object(featurebase, "make_tracked_session", return_value=session):
            valid, error = validate_credentials("fb_test")
        assert valid is expected_valid
        if not expected_valid:
            assert error == "Invalid API Key"


class TestWebhookManagement:
    def test_create_webhook_captures_signing_secret(self) -> None:
        session = _session_with(post=_json_response({"id": "wh1", "secret": "whsec_abc"}))
        with patch.object(featurebase, "make_tracked_session", return_value=session):
            result = create_webhook("fb_test", "https://us.posthog.com/webhook")

        assert result.success is True
        assert result.extra_inputs == {"signing_secret": "whsec_abc"}
        assert result.pending_inputs == []
        payload = session.post.call_args.kwargs["json"]
        assert payload["url"] == "https://us.posthog.com/webhook"
        assert "post.created" in payload["topics"] and "changelog.published" in payload["topics"]

    def test_create_webhook_surfaces_org_limit_error(self) -> None:
        # Featurebase caps webhooks per org and 400s at the cap — the user needs the reason,
        # not a retry loop.
        session = _session_with(post=_json_response({"message": "Webhook limit reached"}, 400))
        with patch.object(featurebase, "make_tracked_session", return_value=session):
            result = create_webhook("fb_test", "https://us.posthog.com/webhook")

        assert result.success is False
        assert result.error == "Webhook limit reached"

    def test_delete_webhook_matches_by_url(self) -> None:
        session = _session_with(
            get=_json_response({"data": [{"id": "wh1", "url": "https://us.posthog.com/webhook"}], "nextCursor": None}),
            delete=_json_response({"id": "wh1", "deleted": True}),
        )
        with patch.object(featurebase, "make_tracked_session", return_value=session):
            result = delete_webhook("fb_test", "https://us.posthog.com/webhook")

        assert result.success is True
        assert "/webhooks/wh1" in session.delete.call_args.args[0]

    def test_delete_webhook_with_no_match_is_success(self) -> None:
        session = _session_with(get=_json_response({"data": [], "nextCursor": None}))
        with patch.object(featurebase, "make_tracked_session", return_value=session):
            result = delete_webhook("fb_test", "https://us.posthog.com/webhook")
        assert result.success is True
        session.delete.assert_not_called()

    def test_sync_webhook_events_patches_drifted_topics(self) -> None:
        session = _session_with(
            get=_json_response(
                {
                    "data": [{"id": "wh1", "url": "https://us.posthog.com/webhook", "topics": ["post.created"]}],
                    "nextCursor": None,
                }
            ),
            patch=_json_response({"id": "wh1"}),
        )
        with patch.object(featurebase, "make_tracked_session", return_value=session):
            result = sync_webhook_events("fb_test", "https://us.posthog.com/webhook", ["post.created", "post.updated"])

        assert result.success is True
        assert session.patch.call_args.kwargs["json"] == {"topics": ["post.created", "post.updated"]}

    def test_sync_webhook_events_noop_when_topics_match(self) -> None:
        session = _session_with(
            get=_json_response(
                {
                    "data": [{"id": "wh1", "url": "https://us.posthog.com/webhook", "topics": ["post.created"]}],
                    "nextCursor": None,
                }
            )
        )
        with patch.object(featurebase, "make_tracked_session", return_value=session):
            result = sync_webhook_events("fb_test", "https://us.posthog.com/webhook", ["post.created"])
        assert result.success is True
        session.patch.assert_not_called()

    def test_get_external_webhook_info(self) -> None:
        session = _session_with(
            get=_json_response(
                {
                    "data": [
                        {
                            "id": "wh1",
                            "url": "https://us.posthog.com/webhook",
                            "topics": ["post.created"],
                            "status": "active",
                            "createdAt": "2026-01-01T00:00:00.000Z",
                        }
                    ],
                    "nextCursor": None,
                }
            )
        )
        with patch.object(featurebase, "make_tracked_session", return_value=session):
            info = get_external_webhook_info("fb_test", "https://us.posthog.com/webhook")

        assert info.exists is True
        assert info.status == "active"
        assert info.enabled_events == ["post.created"]

    def test_get_external_webhook_info_not_found(self) -> None:
        session = _session_with(get=_json_response({"data": [], "nextCursor": None}))
        with patch.object(featurebase, "make_tracked_session", return_value=session):
            info = get_external_webhook_info("fb_test", "https://us.posthog.com/webhook")
        assert info.exists is False
