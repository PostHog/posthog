import json
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from requests import Response
from requests.exceptions import ConnectionError as RequestsConnectionError

from products.warehouse_sources.backend.temporal.data_imports.sources.ably.ably import (
    AblyResumeConfig,
    _add_interval_start,
    _parse_interval_start,
    ably_source,
    get_resource,
    split_api_key,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


class TestSplitApiKey:
    @pytest.mark.parametrize(
        ("api_key", "expected_username", "expected_password"),
        [
            ("app123.key456:secretvalue", "app123.key456", "secretvalue"),
            # A key secret could itself contain a colon; only the first colon is the split point.
            ("app123.key456:secret:with:colons", "app123.key456", "secret:with:colons"),
        ],
    )
    def test_splits_on_first_colon(self, api_key: str, expected_username: str, expected_password: str) -> None:
        username, password = split_api_key(api_key)
        assert username == expected_username
        assert password == expected_password

    def test_missing_colon_yields_empty_password(self) -> None:
        username, password = split_api_key("no-colon-here")
        assert username == "no-colon-here"
        assert password == ""


class TestParseIntervalStart:
    @pytest.mark.parametrize(
        ("interval_id", "expected_iso"),
        [
            ("2024-01-15:14:05", "2024-01-15T14:05:00+00:00"),
            ("2024-01-15:14", "2024-01-15T14:00:00+00:00"),
            ("2024-01-15", "2024-01-15T00:00:00+00:00"),
        ],
    )
    def test_parses_known_granularities(self, interval_id: str, expected_iso: str) -> None:
        parsed = _parse_interval_start(interval_id)
        assert parsed is not None
        assert parsed.isoformat() == expected_iso

    @pytest.mark.parametrize("interval_id", [None, "", "not-a-date", "2024/01/15"])
    def test_returns_none_for_malformed_or_missing(self, interval_id: str | None) -> None:
        assert _parse_interval_start(interval_id) is None


class TestAddIntervalStart:
    def test_adds_parsed_fields(self) -> None:
        row = {"intervalId": "2024-01-15:14", "unit": "hour"}
        result = _add_interval_start(row)
        assert result["interval_start"] == "2024-01-15T14:00:00+00:00"
        # Unix ms — the same unit Ably's start/end stats params take.
        assert result["interval_start_ms"] == 1705327200000

    def test_missing_interval_id_sets_none_rather_than_raising(self) -> None:
        row: dict[str, Any] = {"unit": "hour"}
        result = _add_interval_start(row)
        assert result["interval_start"] is None
        assert result["interval_start_ms"] is None


class TestGetResource:
    def test_full_refresh_has_no_incremental_params(self) -> None:
        resource = get_resource("hour", should_use_incremental_field=False)
        endpoint = resource["endpoint"]
        assert isinstance(endpoint, dict)
        assert "incremental" not in endpoint
        assert resource["write_disposition"] == "replace"
        params = endpoint["params"]
        assert isinstance(params, dict)
        assert params["unit"] == "hour"
        assert params["direction"] == "forwards"

    def test_incremental_sets_start_and_end_params(self) -> None:
        resource = get_resource("day", should_use_incremental_field=True)
        endpoint = resource["endpoint"]
        assert isinstance(endpoint, dict)
        incremental = endpoint["incremental"]
        assert incremental is not None
        assert incremental["start_param"] == "start"
        assert incremental["end_param"] == "end"
        assert incremental["initial_value"] == "0"
        # end_value is bound to "now" at build time — assert it's a plausible ms-epoch, not a fixed literal.
        end_value = incremental["end_value"]
        assert end_value is not None and int(end_value) > 1_700_000_000_000
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}


def _make_http_response(body: list[dict[str, Any]], *, next_url: str | None = None, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    if next_url:
        resp.headers["Link"] = f'<{next_url}>; rel="next"'
    return resp


class TestAblySourceResumeBehavior:
    """End-to-end resume/pagination behaviour of ``ably_source`` via ``rest_api_resource``."""

    def _drive(
        self, manager: MagicMock, responses: list[Response], should_use_incremental_field: bool = False
    ) -> tuple[list[str], list[list[dict[str, Any]]]]:
        sent_urls: list[str] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_urls.append(request.url)
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            resource = ably_source(
                api_key="app.key:secret",
                unit="hour",
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                db_incremental_field_last_value=None,
                should_use_incremental_field=should_use_incremental_field,
            )
            pages = list(resource)
            return sent_urls, pages

    def test_fresh_run_follows_link_header_and_saves_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        next_url = "https://main.realtime.ably.net/stats?start=abc&series=1"
        responses = [
            _make_http_response([{"intervalId": "2024-01-15:14", "unit": "hour"}], next_url=next_url),
            _make_http_response([{"intervalId": "2024-01-15:15", "unit": "hour"}]),
        ]
        sent_urls, pages = self._drive(manager, responses)

        assert sent_urls == ["https://main.realtime.ably.net/stats", next_url]

        flattened = [row for page in pages for row in page]
        assert flattened[0]["interval_start"] == "2024-01-15T14:00:00+00:00"
        assert flattened[1]["interval_start"] == "2024-01-15T15:00:00+00:00"

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [AblyResumeConfig(next_url=next_url)]

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response([{"intervalId": "2024-01-15:14", "unit": "hour"}])]
        self._drive(manager, responses)

        manager.save_state.assert_not_called()

    def test_resume_seeds_paginator_with_saved_next_url(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        resumed_url = "https://main.realtime.ably.net/stats?start=resumed"
        manager.load_state.return_value = AblyResumeConfig(next_url=resumed_url)

        responses = [_make_http_response([{"intervalId": "2024-01-15:16", "unit": "hour"}])]
        sent_urls, _ = self._drive(manager, responses)

        assert sent_urls == [resumed_url]
        manager.load_state.assert_called_once()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response([{"intervalId": "2024-01-15:14", "unit": "hour"}])]
        self._drive(manager, responses)

        manager.load_state.assert_not_called()


def _make_redirect_response(location: str, status_code: int = 302) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.headers["Location"] = location
    resp._content = b""
    return resp


class TestAblyHostPinningAndRedirects:
    """`allowed_hosts=[]` + `allow_redirects=False` keep the Basic-auth credential from
    following a spoofed ``Link: rel="next"`` target or a cross-origin redirect off Ably's host."""

    def _drive(self, sent_urls: list[str], responses: list[Response]) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_urls.append(request.url)
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            resource = ably_source(
                api_key="app.key:secret",
                unit="hour",
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                db_incremental_field_last_value=None,
            )
            list(resource)

    def test_off_origin_next_link_is_rejected_before_sending(self) -> None:
        # A spoofed `Link: rel="next"` pointing off Ably's host must be refused before the
        # request (carrying the Basic-auth key) leaves the process.
        evil_url = "https://evil.example.com/stats?start=abc"
        sent_urls: list[str] = []
        responses = [_make_http_response([{"intervalId": "2024-01-15:14", "unit": "hour"}], next_url=evil_url)]

        with pytest.raises(ValueError, match="disallowed host"):
            self._drive(sent_urls, responses)

        # Only the legitimate first page was ever sent; the off-origin URL was never contacted.
        assert sent_urls == ["https://main.realtime.ably.net/stats"]

    def test_cross_origin_redirect_is_not_followed(self) -> None:
        sent_urls: list[str] = []
        responses = [_make_redirect_response("https://evil.example.com/stats")]

        with pytest.raises(ValueError, match="[Rr]edirect"):
            self._drive(sent_urls, responses)

        # The redirect target was never fetched: send ran once for the base host and stopped.
        assert sent_urls == ["https://main.realtime.ably.net/stats"]


class TestValidateCredentials:
    def test_malformed_key_fails_without_a_request(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.ably.ably.make_tracked_session"
        ) as mock_make_session:
            ok, error = validate_credentials("no-colon-here")

            assert ok is False
            assert error is not None and "malformed" in error.lower()
            mock_make_session.assert_not_called()

    @pytest.mark.parametrize(
        ("status_code", "expect_ok"),
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    def test_status_code_mapping(self, status_code: int, expect_ok: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.ably.ably.make_tracked_session"
        ) as mock_make_session:
            mock_make_session.return_value.get.return_value = MagicMock(status_code=status_code)
            ok, error = validate_credentials("app.key:secret")

            assert ok is expect_ok
            if not expect_ok:
                assert error is not None

    def test_network_error_is_reported_not_raised(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.ably.ably.make_tracked_session"
        ) as mock_make_session:
            mock_make_session.return_value.get.side_effect = RequestsConnectionError("boom")
            ok, error = validate_credentials("app.key:secret")

            assert ok is False
            assert error == "boom"
