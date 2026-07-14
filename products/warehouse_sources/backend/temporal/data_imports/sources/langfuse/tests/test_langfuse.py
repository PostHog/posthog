import json
from datetime import UTC, datetime
from typing import Any, Optional

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse import langfuse as langfuse_module
from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.langfuse import (
    LangfuseHostNotAllowedError,
    LangfuseResponseTooLargeError,
    LangfuseResumeConfig,
    get_rows,
    langfuse_source,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.settings import LANGFUSE_ENDPOINTS


def _response(*, status_code: int = 200, json_data: Any = None, text: str = "") -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.is_redirect = status_code in (301, 302, 303, 307, 308)
    response.is_permanent_redirect = status_code in (301, 308)
    response.text = text
    response.json.return_value = json_data
    response.headers = {}
    # get_rows streams the body via iter_content (see _read_json_capped), so feed the
    # serialized payload back one chunk at a time.
    payload = json.dumps(json_data).encode() if json_data is not None else text.encode()
    response.iter_content.return_value = iter([payload] if payload else [])
    return response


def _page(rows: list[dict[str, Any]], *, total_pages: Optional[int], page: int = 1) -> mock.MagicMock:
    return _response(
        json_data={"data": rows, "meta": {"page": page, "limit": 100, "totalItems": 0, "totalPages": total_pages}}
    )


def _cursor_page(rows: list[dict[str, Any]], cursor: Optional[str]) -> mock.MagicMock:
    return _response(json_data={"data": rows, "meta": {"cursor": cursor}})


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (None, "https://cloud.langfuse.com"),
            ("", "https://cloud.langfuse.com"),
            ("   ", "https://cloud.langfuse.com"),
            ("https://cloud.langfuse.com", "https://cloud.langfuse.com"),
            ("https://us.cloud.langfuse.com/", "https://us.cloud.langfuse.com"),
            ("us.cloud.langfuse.com", "https://us.cloud.langfuse.com"),
            ("http://langfuse.internal.example.com", "http://langfuse.internal.example.com"),
            ("https://langfuse.example.com/api", "https://langfuse.example.com"),
            ("https://langfuse.example.com/api/public", "https://langfuse.example.com"),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_host(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            # urlparse reads the host as cloud.langfuse.com, but requests connects to the
            # userinfo host — reject the backslash/userinfo SSRF bypass outright.
            "https://169.254.169.254\\@cloud.langfuse.com",
            "https://169.254.169.254%5c@cloud.langfuse.com",
            "https://user@cloud.langfuse.com",
        ],
    )
    def test_rejects_userinfo_ssrf_bypass(self, raw):
        with pytest.raises(ValueError):
            normalize_host(raw)

    def test_rejects_http_on_cloud(self):
        # Credentials ride as HTTP Basic auth, so plaintext http must be refused on cloud.
        with mock.patch.object(langfuse_module, "is_cloud", return_value=True):
            with pytest.raises(ValueError):
                normalize_host("http://langfuse.example.com")

    def test_allows_http_when_self_hosted(self):
        with mock.patch.object(langfuse_module, "is_cloud", return_value=False):
            assert normalize_host("http://langfuse.internal.example.com") == "http://langfuse.internal.example.com"


class TestValidateCredentials:
    def _patch_session(self, response=None, raises=None):
        session = mock.MagicMock()
        if raises is not None:
            session.get.side_effect = raises
        else:
            session.get.return_value = response
        return mock.patch.object(langfuse_module, "make_tracked_session", return_value=session)

    def test_success(self):
        with self._patch_session(_response(status_code=200)):
            assert validate_credentials(None, "pk", "sk") == (True, None)

    def test_invalid_keys(self):
        with self._patch_session(_response(status_code=401)):
            valid, msg = validate_credentials(None, "pk", "sk")
            assert valid is False
            assert msg is not None and "Invalid Langfuse" in msg

    def test_403_at_source_create_is_accepted(self):
        with self._patch_session(_response(status_code=403)):
            assert validate_credentials(None, "pk", "sk", schema_name=None) == (True, None)

    def test_403_for_scoped_probe_fails(self):
        with self._patch_session(_response(status_code=403)):
            valid, msg = validate_credentials(None, "pk", "sk", schema_name="traces")
            assert valid is False
            assert msg is not None

    def test_request_exception_returns_failure(self):
        with self._patch_session(raises=requests.exceptions.ConnectionError("boom")):
            valid, msg = validate_credentials(None, "pk", "sk")
            assert valid is False
            assert "boom" in (msg or "")

    def test_rejects_redirect_response(self):
        with self._patch_session(_response(status_code=302)) as patched:
            valid, msg = validate_credentials(None, "pk", "sk")
            assert valid is False
            assert msg == langfuse_module.HOST_NOT_ALLOWED_ERROR
            assert patched.return_value.get.call_args.kwargs["allow_redirects"] is False

    def test_blocks_unsafe_host(self):
        with (
            mock.patch.object(langfuse_module, "_is_host_safe", return_value=(False, "internal address")),
            self._patch_session(_response(status_code=200)) as patched,
        ):
            valid, msg = validate_credentials("http://10.0.0.1", "pk", "sk", team_id=99)
            assert valid is False
            assert msg == "internal address"
            patched.return_value.get.assert_not_called()

    def test_probe_uses_basic_auth_against_configured_host(self):
        with self._patch_session(_response(status_code=200)) as patched:
            validate_credentials("https://us.cloud.langfuse.com", "pk", "sk")
            call = patched.return_value.get.call_args
            assert call.args[0] == "https://us.cloud.langfuse.com/api/public/projects"
            assert call.kwargs["auth"] == ("pk", "sk")
            # Stream so a hostile host can't force the probe to buffer a huge body.
            assert call.kwargs["stream"] is True

    def test_unknown_status_reads_bounded_body_not_text(self):
        # A non-2xx/401/403 status reads the error message from a bounded stream — never the
        # unbounded response.text/.json() a hostile host could inflate. Distinct values on each
        # source catch a revert to the unbounded reads.
        resp = _response(status_code=500)
        resp.iter_content.return_value = iter([b'{"message": "from-stream"}'])
        resp.text = "from-text"
        resp.json.return_value = {"message": "from-json"}
        with self._patch_session(resp):
            valid, msg = validate_credentials(None, "pk", "sk")
        assert valid is False
        assert msg == "from-stream"


class TestLangfuseSourceResponse:
    @pytest.mark.parametrize("endpoint", list(LANGFUSE_ENDPOINTS.keys()))
    def test_response_shape(self, endpoint):
        config = LANGFUSE_ENDPOINTS[endpoint]
        response = langfuse_source(
            host=None,
            public_key="pk",
            secret_key="sk",
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(),
            team_id=1,
        )
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == config.sort_mode
        if config.partition_key:
            assert response.partition_keys == [config.partition_key]
            assert response.partition_mode == "datetime"
            assert response.partition_format == "month"
        else:
            assert response.partition_keys is None


class TestGetRows:
    def _run(
        self,
        manager,
        responses,
        endpoint="traces",
        team_id=1,
        host=None,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
    ):
        session = mock.MagicMock()
        session.get.side_effect = responses
        with mock.patch.object(langfuse_module, "make_tracked_session", return_value=session):
            rows: list[dict[str, Any]] = []
            for batch in get_rows(
                host=host,
                public_key="pk",
                secret_key="sk",
                endpoint=endpoint,
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
                team_id=team_id,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
            ):
                rows.extend(batch)
        return rows, session

    def _manager(self, resume_config: Optional[LangfuseResumeConfig] = None) -> mock.MagicMock:
        manager = mock.MagicMock()
        manager.can_resume.return_value = resume_config is not None
        manager.load_state.return_value = resume_config
        return manager

    def test_paginates_via_meta_total_pages(self):
        manager = self._manager()
        page1 = _page([{"id": "1"}, {"id": "2"}], total_pages=2, page=1)
        page2 = _page([{"id": "3"}], total_pages=2, page=2)
        rows, session = self._run(manager, [page1, page2])

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        first_params = session.get.call_args_list[0].kwargs["params"]
        second_params = session.get.call_args_list[1].kwargs["params"]
        assert first_params["page"] == 1
        assert second_params["page"] == 2
        # Traces are pulled in ascending timestamp order so page pagination stays stable.
        assert first_params["orderBy"] == "timestamp.asc"

    def test_cursor_pagination_follows_meta_cursor(self):
        manager = self._manager()
        page1 = _cursor_page([{"id": "a"}], "cursor-1")
        page2 = _cursor_page([{"id": "b"}], None)
        rows, session = self._run(manager, [page1, page2], endpoint="observations")

        assert [r["id"] for r in rows] == ["a", "b"]
        first_params = session.get.call_args_list[0].kwargs["params"]
        second_params = session.get.call_args_list[1].kwargs["params"]
        assert "cursor" not in first_params
        assert second_params["cursor"] == "cursor-1"
        # Observations max out the 1,000-row page size and request every field group.
        assert first_params["limit"] == 1000
        assert "usage" in first_params["fields"]

    def test_incremental_filter_is_sent_as_iso8601_z(self):
        manager = self._manager()
        _rows, session = self._run(
            manager,
            [_page([{"id": "1"}], total_pages=1)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        )
        params = session.get.call_args.kwargs["params"]
        assert params["fromTimestamp"] == "2026-01-02T03:04:05.000Z"

    def test_full_refresh_endpoint_sends_no_incremental_filter(self):
        manager = self._manager()
        _rows, session = self._run(
            manager,
            [_page([{"name": "p"}], total_pages=1)],
            endpoint="prompts",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 2, tzinfo=UTC),
        )
        params = session.get.call_args.kwargs["params"]
        assert "fromTimestamp" not in params
        assert "fromStartTime" not in params

    def test_saves_state_after_yielding_each_page(self):
        manager = self._manager()
        page1 = _page([{"id": "1"}], total_pages=2, page=1)
        page2 = _page([{"id": "2"}], total_pages=2, page=2)
        self._run(manager, [page1, page2])

        # State saved once (after page 1, pointing at page 2); the last page saves nothing.
        assert manager.save_state.call_count == 1
        saved = manager.save_state.call_args.args[0]
        assert isinstance(saved, LangfuseResumeConfig)
        assert saved.next_page == 2

    def test_saves_cursor_state_with_incremental_window(self):
        manager = self._manager()
        page1 = _cursor_page([{"id": "a"}], "cursor-1")
        page2 = _cursor_page([{"id": "b"}], None)
        self._run(
            manager,
            [page1, page2],
            endpoint="observations",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 2, tzinfo=UTC),
        )
        saved = manager.save_state.call_args.args[0]
        assert saved.next_cursor == "cursor-1"
        assert saved.incremental_from == "2026-01-02T00:00:00.000Z"

    def test_resumes_from_saved_page_and_window(self):
        # The interrupted run's window must be reused verbatim, not rebuilt from the (already
        # advanced) DB watermark — otherwise page positions shift and rows get skipped.
        manager = self._manager(LangfuseResumeConfig(next_page=3, incremental_from="2026-01-01T00:00:00.000Z"))
        rows, session = self._run(
            manager,
            [_page([{"id": "9"}], total_pages=3, page=3)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 2, 1, tzinfo=UTC),
        )
        params = session.get.call_args.kwargs["params"]
        assert params["page"] == 3
        assert params["fromTimestamp"] == "2026-01-01T00:00:00.000Z"
        assert [r["id"] for r in rows] == ["9"]

    def test_resumes_from_saved_cursor(self):
        manager = self._manager(LangfuseResumeConfig(next_cursor="cursor-9"))
        rows, session = self._run(manager, [_cursor_page([{"id": "z"}], None)], endpoint="observations")
        assert session.get.call_args.kwargs["params"]["cursor"] == "cursor-9"
        assert [r["id"] for r in rows] == ["z"]

    def test_empty_page_terminates(self):
        manager = self._manager()
        rows, session = self._run(manager, [_page([], total_pages=5)])
        assert rows == []
        assert session.get.call_count == 1
        manager.save_state.assert_not_called()

    def test_rejects_redirect_response(self):
        manager = self._manager()
        with pytest.raises(LangfuseHostNotAllowedError):
            self._run(manager, [_response(status_code=302)])

    def test_passes_allow_redirects_false(self):
        manager = self._manager()
        _rows, session = self._run(manager, [_page([{"id": "1"}], total_pages=1)])
        assert session.get.call_args.kwargs["allow_redirects"] is False
        # Streaming is what lets _read_json_capped bound the body — guard it isn't dropped.
        assert session.get.call_args.kwargs["stream"] is True

    def test_raises_when_host_not_allowed(self):
        manager = self._manager()
        with mock.patch.object(langfuse_module, "_is_host_safe", return_value=(False, "internal address")):
            with pytest.raises(LangfuseHostNotAllowedError):
                self._run(manager, [_page([{"id": "1"}], total_pages=1)])

    @pytest.mark.parametrize("status_code", [429, 503])
    def test_retries_retryable_status_then_succeeds(self, status_code):
        # End-to-end: a retryable status raises LangfuseRetryableError, tenacity retries, and
        # the subsequent 200 yields rows. Guards against dropping the retry predicate.
        manager = self._manager()
        responses = [_response(status_code=status_code), _page([{"id": "1"}], total_pages=1)]
        with mock.patch.object(langfuse_module, "_retry_wait", return_value=0):
            rows, session = self._run(manager, responses)
        assert [r["id"] for r in rows] == ["1"]
        assert session.get.call_count == 2

    def test_non_retryable_client_error_raises(self):
        manager = self._manager()
        error_response = _response(status_code=401, text="unauthorized")
        error_response.raise_for_status.side_effect = requests.HTTPError("401 Client Error", response=error_response)
        with pytest.raises(requests.HTTPError):
            self._run(manager, [error_response])

    def test_stops_at_max_pages(self):
        # A host that never reports totalPages and always returns a nonempty page would page
        # forever without the cap, tying up the worker until the activity timeout.
        manager = self._manager()
        session = mock.MagicMock()
        session.get.side_effect = lambda *a, **k: _page([{"id": "x"}], total_pages=None)
        with (
            mock.patch.object(langfuse_module, "make_tracked_session", return_value=session),
            mock.patch.object(langfuse_module, "MAX_PAGES", 3),
        ):
            batches = list(
                get_rows(
                    host=None,
                    public_key="pk",
                    secret_key="sk",
                    endpoint="traces",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                    team_id=1,
                )
            )
        assert len(batches) == 3
        assert session.get.call_count == 3

    def test_stops_on_repeated_cursor(self):
        # A cursor endpoint that keeps echoing the same cursor would otherwise loop forever.
        manager = self._manager()
        session = mock.MagicMock()
        session.get.side_effect = lambda *a, **k: _cursor_page([{"id": "a"}], "same-cursor")
        with mock.patch.object(langfuse_module, "make_tracked_session", return_value=session):
            batches = list(
                get_rows(
                    host=None,
                    public_key="pk",
                    secret_key="sk",
                    endpoint="observations",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                    team_id=1,
                )
            )
        # First page is followed once; the repeated cursor on the second page stops the loop.
        assert session.get.call_count == 2
        assert len(batches) == 2

    def test_rejects_oversized_response(self):
        # A hostile host can ignore the page-size limit and stream back an enormous body.
        manager = self._manager()
        with mock.patch.object(langfuse_module, "MAX_RESPONSE_BYTES", 4):
            with pytest.raises(LangfuseResponseTooLargeError):
                self._run(manager, [_page([{"id": "1"}], total_pages=1)])
