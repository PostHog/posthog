import json
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse import langfuse as langfuse_module
from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.langfuse import (
    HOST_NOT_ALLOWED_ERROR,
    HTTP_NOT_ALLOWED_ERROR,
    LangfuseResumeConfig,
    LangfuseRetryableError,
    _from_filter_value,
    _parse_retry_after,
    _retry_wait,
    get_rows,
    langfuse_source,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.settings import LANGFUSE_ENDPOINTS


def _response(
    *,
    status_code: int = 200,
    json_data: Any = None,
    text: str = "",
    headers: Any = None,
    body_chunks: Optional[list[bytes]] = None,
) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.is_redirect = status_code in (302, 303, 307)
    response.is_permanent_redirect = status_code in (301, 308)
    response.text = text
    response.json.return_value = json_data
    response.headers = headers or {}
    # get_rows streams the body (stream=True) and JSON-decodes the bytes, so the body must flow
    # through iter_content rather than response.json(). body_chunks lets a test drip the body in
    # pieces (e.g. to exceed the size cap).
    if body_chunks is None:
        payload = json.dumps(json_data).encode() if json_data is not None else text.encode()
        body_chunks = [payload] if payload else []
    response.iter_content.return_value = body_chunks
    return response


def _page(items: list[dict[str, Any]], *, page: int, total_pages: int) -> mock.MagicMock:
    return _response(json_data={"data": items, "meta": {"page": page, "limit": 50, "totalPages": total_pages}})


def _cursor_page(items: list[dict[str, Any]], *, cursor: Optional[str]) -> mock.MagicMock:
    return _response(json_data={"data": items, "meta": {"cursor": cursor}})


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (None, "https://cloud.langfuse.com"),
            ("", "https://cloud.langfuse.com"),
            ("us.cloud.langfuse.com", "https://us.cloud.langfuse.com"),
            ("https://cloud.langfuse.com/", "https://cloud.langfuse.com"),
            ("  langfuse.example.com  ", "https://langfuse.example.com"),
            ("http://langfuse.example.com:3000/", "http://langfuse.example.com:3000"),
        ],
    )
    def test_normalize_host(self, raw, expected):
        assert normalize_host(raw) == expected


class TestFromFilterValue:
    def test_applies_lookback_and_formats_iso_z(self):
        # Traces declare a 1h lookback: a watermark of 12:00 must re-pull from 11:00 so
        # late-arriving rows (ingestion lag) aren't skipped forever.
        value = _from_filter_value(
            LANGFUSE_ENDPOINTS["traces"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 12, 0, 0, tzinfo=UTC),
            incremental_field="timestamp",
        )
        assert value == "2026-03-04T11:00:00Z"

    def test_date_value_is_supported(self):
        value = _from_filter_value(
            LANGFUSE_ENDPOINTS["traces"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 3, 4),
            incremental_field="timestamp",
        )
        assert value == "2026-03-03T23:00:00Z"

    @pytest.mark.parametrize(
        "should_use, last_value",
        [
            (False, datetime(2026, 3, 4, tzinfo=UTC)),
            (True, None),
        ],
    )
    def test_full_or_first_sync_has_no_filter(self, should_use, last_value):
        value = _from_filter_value(
            LANGFUSE_ENDPOINTS["traces"],
            should_use_incremental_field=should_use,
            db_incremental_field_last_value=last_value,
            incremental_field="timestamp",
        )
        assert value is None

    def test_unsupported_incremental_field_raises(self):
        with pytest.raises(ValueError):
            _from_filter_value(
                LANGFUSE_ENDPOINTS["traces"],
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
                incremental_field="updatedAt",
            )

    def test_full_refresh_endpoint_never_filters(self):
        value = _from_filter_value(
            LANGFUSE_ENDPOINTS["datasets"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field=None,
        )
        assert value is None


class TestValidateCredentials:
    def _patch_session(self, response=None, raises=None):
        session = mock.MagicMock()
        if raises is not None:
            session.get.side_effect = raises
        else:
            session.get.return_value = response
        return mock.patch.object(langfuse_module, "make_tracked_session", return_value=session)

    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_msg_substr",
        [
            (200, True, None),
            (401, False, "Invalid Langfuse API keys"),
            (403, False, "Invalid Langfuse API keys"),
        ],
    )
    def test_status_code_mapping(self, status_code, expected_valid, expected_msg_substr):
        with self._patch_session(_response(status_code=status_code)):
            valid, msg = validate_credentials("https://cloud.langfuse.com", "pk-lf-x", "sk-lf-x")
            assert valid is expected_valid
            if expected_msg_substr is None:
                assert msg is None
            else:
                assert expected_msg_substr in (msg or "")

    @pytest.mark.parametrize(
        "public_key, secret_key, expected_msg",
        [
            ("", "sk-lf-x", "Missing public key"),
            ("pk-lf-x", "  ", "Missing secret key"),
        ],
    )
    def test_missing_keys_short_circuit(self, public_key, secret_key, expected_msg):
        valid, msg = validate_credentials("https://cloud.langfuse.com", public_key, secret_key)
        assert valid is False
        assert msg == expected_msg

    def test_uses_basic_auth_and_no_redirects(self):
        with self._patch_session(_response(status_code=200)) as patched:
            validate_credentials("https://cloud.langfuse.com", " pk-lf-x ", " sk-lf-x ", team_id=None)
            kwargs = patched.return_value.get.call_args.kwargs
            assert kwargs["auth"] == ("pk-lf-x", "sk-lf-x")
            assert kwargs["allow_redirects"] is False
            # Adapter-level retries must stay disabled: urllib3 honors Retry-After uncapped, so a
            # hostile host could park the worker before the bounded tenacity policy runs.
            assert patched.call_args.kwargs["retry"].total == 0

    def test_rejects_redirect_response(self):
        with self._patch_session(_response(status_code=302)):
            valid, msg = validate_credentials("https://cloud.langfuse.com", "pk-lf-x", "sk-lf-x")
            assert valid is False
            assert "unexpected redirect" in (msg or "")

    def test_rejects_plaintext_http(self):
        with self._patch_session(_response(status_code=200)) as patched:
            valid, msg = validate_credentials("http://langfuse.example.com", "pk-lf-x", "sk-lf-x")
            assert valid is False
            assert msg == HTTP_NOT_ALLOWED_ERROR
            patched.return_value.get.assert_not_called()

    def test_blocks_unsafe_host(self):
        with (
            mock.patch.object(langfuse_module, "_is_host_safe", return_value=(False, "internal address")),
            self._patch_session(_response(status_code=200)) as patched,
        ):
            valid, msg = validate_credentials("https://10.0.0.1", "pk-lf-x", "sk-lf-x", team_id=99)
            assert valid is False
            assert msg == "internal address"
            patched.return_value.get.assert_not_called()


class TestLangfuseSourceResponse:
    @pytest.mark.parametrize(
        "endpoint, primary_keys, partition_key, sort_mode",
        [
            ("traces", ["id"], "timestamp", "asc"),
            ("observations", ["id"], "startTime", "desc"),
            ("scores", ["id"], "timestamp", "desc"),
            ("sessions", ["id"], "createdAt", "desc"),
            ("prompts", ["name"], None, "desc"),
            ("datasets", ["id"], None, "desc"),
            ("dataset_items", ["id"], "createdAt", "desc"),
            ("models", ["id"], None, "desc"),
        ],
    )
    def test_response_shape(self, endpoint, primary_keys, partition_key, sort_mode):
        response = langfuse_source(
            host="https://cloud.langfuse.com",
            public_key="pk-lf-x",
            secret_key="sk-lf-x",
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(),
            team_id=1,
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode
        if partition_key:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None


class TestGetRows:
    def _run(self, manager, responses, endpoint="traces", **kwargs):
        session = mock.MagicMock()
        session.get.side_effect = responses
        with mock.patch.object(langfuse_module, "make_tracked_session", return_value=session):
            rows: list[dict[str, Any]] = []
            for batch in get_rows(
                host="https://cloud.langfuse.com",
                public_key="pk-lf-x",
                secret_key="sk-lf-x",
                endpoint=endpoint,
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
                team_id=1,
                **kwargs,
            ):
                rows.extend(batch)
        return rows, session

    def _manager(self, resume_state: Optional[LangfuseResumeConfig] = None) -> mock.MagicMock:
        manager = mock.MagicMock()
        manager.can_resume.return_value = resume_state is not None
        manager.load_state.return_value = resume_state
        return manager

    def test_page_pagination_walks_all_pages(self):
        manager = self._manager()
        rows, session = self._run(
            manager,
            [
                _page([{"id": "t1"}, {"id": "t2"}], page=1, total_pages=2),
                _page([{"id": "t3"}], page=2, total_pages=2),
            ],
        )
        assert [r["id"] for r in rows] == ["t1", "t2", "t3"]
        assert session.get.call_args_list[0].kwargs["params"]["page"] == 1
        assert session.get.call_args_list[1].kwargs["params"]["page"] == 2

    def test_page_pagination_saves_next_page_after_yield(self):
        manager = self._manager()
        self._run(
            manager,
            [
                _page([{"id": "t1"}], page=1, total_pages=2),
                _page([{"id": "t2"}], page=2, total_pages=2),
            ],
        )
        # Only the non-final page checkpoints (a crash re-yields the last page; merge dedupes),
        # and it points at the NEXT page to fetch.
        assert manager.save_state.call_count == 1
        saved = manager.save_state.call_args.args[0]
        assert isinstance(saved, LangfuseResumeConfig)
        assert saved.page == 2

    def test_traces_request_pins_ascending_order_and_incremental_filter(self):
        # The pipeline checkpoints the incremental watermark per batch for sort_mode="asc";
        # dropping the orderBy pin or the from-filter would corrupt it.
        manager = self._manager()
        _rows, session = self._run(
            manager,
            [_page([{"id": "t1"}], page=1, total_pages=1)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 12, 0, 0, tzinfo=UTC),
            incremental_field="timestamp",
        )
        params = session.get.call_args.kwargs["params"]
        assert params["orderBy"] == "timestamp.asc"
        assert params["fromTimestamp"] == "2026-03-04T11:00:00Z"
        assert session.get.call_args.kwargs["auth"] == ("pk-lf-x", "sk-lf-x")
        assert session.get.call_args.kwargs["allow_redirects"] is False

    def test_cursor_pagination_follows_cursor_until_absent(self):
        manager = self._manager()
        rows, session = self._run(
            manager,
            [
                _cursor_page([{"id": "o1"}], cursor="abc"),
                _cursor_page([{"id": "o2"}], cursor=None),
            ],
            endpoint="observations",
        )
        assert [r["id"] for r in rows] == ["o1", "o2"]
        assert "cursor" not in session.get.call_args_list[0].kwargs["params"]
        assert session.get.call_args_list[1].kwargs["params"]["cursor"] == "abc"

    def test_cursor_request_keeps_field_selection_and_filter_on_every_page(self):
        manager = self._manager()
        _rows, session = self._run(
            manager,
            [
                _cursor_page([{"id": "o1"}], cursor="abc"),
                _cursor_page([{"id": "o2"}], cursor=None),
            ],
            endpoint="observations",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 12, 0, 0, tzinfo=UTC),
            incremental_field="startTime",
        )
        for call in session.get.call_args_list:
            assert call.kwargs["params"]["fromStartTime"] == "2026-03-04T11:00:00Z"
            assert "io" in call.kwargs["params"]["fields"]
            assert call.kwargs["params"]["limit"] == 1000

    def test_resume_reuses_saved_page_and_from_value(self):
        # The watermark can advance mid-run; the resumed query must reuse the ORIGINAL
        # from-filter or the saved page number points into a different result set.
        manager = self._manager(LangfuseResumeConfig(page=3, from_value="2026-01-01T00:00:00Z"))
        _rows, session = self._run(
            manager,
            [_page([{"id": "t9"}], page=3, total_pages=3)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="timestamp",
        )
        params = session.get.call_args.kwargs["params"]
        assert params["page"] == 3
        assert params["fromTimestamp"] == "2026-01-01T00:00:00Z"

    def test_resume_from_saved_cursor(self):
        manager = self._manager(LangfuseResumeConfig(cursor="saved-cursor"))
        rows, session = self._run(
            manager,
            [_cursor_page([{"id": "o9"}], cursor=None)],
            endpoint="observations",
        )
        assert session.get.call_args.kwargs["params"]["cursor"] == "saved-cursor"
        assert [r["id"] for r in rows] == ["o9"]

    def test_empty_page_terminates(self):
        manager = self._manager()
        rows, session = self._run(manager, [_page([], page=1, total_pages=5)])
        assert rows == []
        assert session.get.call_count == 1
        manager.save_state.assert_not_called()

    def test_missing_total_pages_stops_instead_of_looping(self):
        manager = self._manager()
        rows, session = self._run(manager, [_response(json_data={"data": [{"id": "t1"}], "meta": {}})])
        assert [r["id"] for r in rows] == ["t1"]
        assert session.get.call_count == 1

    def test_rejects_plaintext_http_before_request(self):
        manager = self._manager()
        session = mock.MagicMock()
        with (
            mock.patch.object(langfuse_module, "make_tracked_session", return_value=session),
            pytest.raises(langfuse_module.LangfuseHostNotAllowedError) as exc,
        ):
            list(
                get_rows(
                    host="http://langfuse.example.com",
                    public_key="pk-lf-x",
                    secret_key="sk-lf-x",
                    endpoint="traces",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                    team_id=1,
                )
            )
        assert HTTP_NOT_ALLOWED_ERROR in str(exc.value)
        session.get.assert_not_called()

    def test_unsafe_host_error_is_marked_non_retryable(self):
        manager = self._manager()
        with (
            mock.patch.object(langfuse_module, "_is_host_safe", return_value=(False, "internal address")),
            pytest.raises(langfuse_module.LangfuseHostNotAllowedError) as exc,
        ):
            self._run(manager, [_page([{"id": "t1"}], page=1, total_pages=1)])
        assert HOST_NOT_ALLOWED_ERROR in str(exc.value)

    def test_redirect_response_is_refused(self):
        manager = self._manager()
        with pytest.raises(langfuse_module.LangfuseHostNotAllowedError) as exc:
            self._run(manager, [_response(status_code=302)])
        assert HOST_NOT_ALLOWED_ERROR in str(exc.value)

    def test_disables_adapter_retries(self):
        # urllib3 honors Retry-After uncapped, so a hostile host could park the worker before the
        # bounded tenacity policy runs. The sync session must opt out of adapter-level retries.
        manager = self._manager()
        session = mock.MagicMock()
        session.get.side_effect = [_page([], page=1, total_pages=1)]
        with mock.patch.object(langfuse_module, "make_tracked_session", return_value=session) as mts:
            list(
                get_rows(
                    host="https://cloud.langfuse.com",
                    public_key="pk-lf-x",
                    secret_key="sk-lf-x",
                    endpoint="traces",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                    team_id=1,
                )
            )
        assert mts.call_args.kwargs["retry"].total == 0

    @pytest.mark.parametrize(
        "attr, value, chunks",
        [
            ("MAX_RESPONSE_BYTES", 4, [b"aaaa", b"aaaa"]),  # decoded body past the byte cap
            ("MAX_TRANSFER_SECONDS", -1, [b"a"]),  # transfer past the wall-clock deadline
        ],
    )
    def test_response_over_limit_raises_non_retryable(self, attr, value, chunks):
        # A hostile/self-hosted host could stream an unbounded or slow-drip body and pin a shared
        # worker. The read must abort past either cap before parsing JSON, with a non-retryable
        # error (retrying can't shrink or speed up the body). A single queued response also proves
        # no retry happens: a retry would consume a second one and raise StopIteration instead.
        manager = self._manager()
        with (
            mock.patch.object(langfuse_module, attr, value),
            pytest.raises(langfuse_module.LangfuseResponseTooLargeError) as exc,
        ):
            self._run(manager, [_response(body_chunks=chunks)])
        assert langfuse_module.RESPONSE_LIMIT_ERROR in str(exc.value)

    def test_repeated_cursor_raises_without_checkpointing_it(self):
        # A hostile host that echoes back the cursor it was given would otherwise re-fetch the same
        # page until the activity timeout. The run must abort (non-retryable) and never checkpoint
        # the poisoned cursor — a saved checkpoint would make every retry loop on it too.
        manager = self._manager()
        with pytest.raises(langfuse_module.LangfusePaginationError) as exc:
            self._run(
                manager,
                [
                    _cursor_page([{"id": "o1"}], cursor="loop"),
                    _cursor_page([{"id": "o2"}], cursor="loop"),
                ],
                endpoint="observations",
            )
        assert langfuse_module.REPEATED_CURSOR_ERROR in str(exc.value)
        # Only the first page's (legitimate) continuation was saved.
        assert manager.save_state.call_count == 1

    def test_page_limit_raises_after_checkpointing_next_page(self):
        # A hostile host reporting ever-more totalPages would otherwise keep the loop alive until
        # the activity timeout. The run must abort at the cap — retryably, with the next page
        # already checkpointed, so a legitimately huge sync continues on the next attempt.
        manager = self._manager()
        with (
            mock.patch.object(langfuse_module, "MAX_PAGES_PER_RUN", 2),
            pytest.raises(langfuse_module.LangfusePaginationError) as exc,
        ):
            self._run(
                manager,
                [
                    _page([{"id": "t1"}], page=1, total_pages=10),
                    _page([{"id": "t2"}], page=2, total_pages=10),
                ],
            )
        assert langfuse_module.PAGE_LIMIT_ERROR in str(exc.value)
        assert manager.save_state.call_args.args[0].page == 3

    def test_proactive_rewindow_advances_from_filter_before_deep_offset(self):
        # Traces 422 on deep offsets, so before reaching the depth ceiling the sync must advance
        # fromTimestamp to the last row's timestamp and reset to page 1 instead of paging deeper.
        manager = self._manager()
        with mock.patch.object(LANGFUSE_ENDPOINTS["traces"], "rewindow_after_pages", 2):
            rows, session = self._run(
                manager,
                [
                    _page([{"id": "t1", "timestamp": "2026-01-01T00:00:01Z"}], page=1, total_pages=10),
                    _page([{"id": "t2", "timestamp": "2026-01-01T00:00:02Z"}], page=2, total_pages=10),
                    _page([{"id": "t3", "timestamp": "2026-01-01T00:00:03Z"}], page=1, total_pages=1),
                ],
            )
        assert [r["id"] for r in rows] == ["t1", "t2", "t3"]
        # After page 2 (== threshold) the next request re-windows: page back to 1, fromTimestamp
        # advanced to the last row seen rather than an offset of page 3.
        third = session.get.call_args_list[2].kwargs["params"]
        assert third["page"] == 1
        assert third["fromTimestamp"] == "2026-01-01T00:00:02Z"
        # The re-window checkpoint points at the fresh shallow window so a crash resumes below the
        # 422 ceiling, never at the deep page.
        saved = manager.save_state.call_args.args[0]
        assert saved.page == 1
        assert saved.from_value == "2026-01-01T00:00:02Z"

    def test_422_triggers_rewindow_instead_of_aborting(self):
        # A 422 (Langfuse's real deep-offset ceiling, hit before our proactive threshold) must be a
        # re-window signal, not a fatal error that aborts the whole traces sync.
        manager = self._manager()
        rows, session = self._run(
            manager,
            [
                _page([{"id": "t1", "timestamp": "2026-01-01T00:00:01Z"}], page=1, total_pages=100),
                _response(status_code=422, text="deep pagination not allowed"),
                _page([{"id": "t2", "timestamp": "2026-01-01T00:00:02Z"}], page=1, total_pages=1),
            ],
        )
        assert [r["id"] for r in rows] == ["t1", "t2"]
        # The request after the 422 restarts at page 1 with the lower bound advanced past the last
        # row we managed to read.
        recovered = session.get.call_args_list[2].kwargs["params"]
        assert recovered["page"] == 1
        assert recovered["fromTimestamp"] == "2026-01-01T00:00:01Z"

    def test_rewindow_bails_when_a_single_timestamp_fills_the_window(self):
        # If more rows share one timestamp than a window can page past, advancing the lower bound to
        # that same timestamp can't make progress — bail (non-retryable) rather than loop forever.
        manager = self._manager()
        with (
            mock.patch.object(LANGFUSE_ENDPOINTS["traces"], "rewindow_after_pages", 1),
            pytest.raises(langfuse_module.LangfusePaginationError) as exc,
        ):
            self._run(
                manager,
                [
                    _page([{"id": "a", "timestamp": "2026-01-01T00:00:01Z"}], page=1, total_pages=5),
                    _page([{"id": "b", "timestamp": "2026-01-01T00:00:01Z"}], page=1, total_pages=5),
                ],
            )
        assert langfuse_module.REWINDOW_STUCK_ERROR in str(exc.value)


class TestRetryBehavior:
    @pytest.mark.parametrize(
        "headers, expected",
        [
            ({"Retry-After": "5"}, 5.0),
            ({"Retry-After": "100000"}, 120.0),  # capped
            ({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, None),  # HTTP-date ignored
            ({}, None),
        ],
    )
    def test_parse_retry_after(self, headers, expected):
        assert _parse_retry_after(_response(headers=headers)) == expected

    def test_retry_wait_prefers_retry_after(self):
        state = mock.MagicMock()
        state.outcome.exception.return_value = LangfuseRetryableError("rate limited", retry_after=7.0)
        assert _retry_wait(state) == 7.0
