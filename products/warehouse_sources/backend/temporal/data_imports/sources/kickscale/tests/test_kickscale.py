import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, Mock, patch

from parameterized import parameterized
from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.kickscale.kickscale import (
    KickscaleAuth,
    KickscalePageNumberPaginator,
    KickscaleResumeConfig,
    _client_config,
    _format_kickscale_datetime,
    get_resource,
    kickscale_source,
    validate_credentials,
)


class TestKickscaleAuth:
    def test_sets_both_headers(self) -> None:
        auth = KickscaleAuth(api_key="key-1", client_id="client-1")
        request = Request(method="GET", url="https://api.kickscale.com/meetings").prepare()

        auth(request)

        assert request.headers["api-key"] == "key-1"
        assert request.headers["client-id"] == "client-1"

    def test_secret_values_reports_both_credentials(self) -> None:
        auth = KickscaleAuth(api_key="key-1", client_id="client-1")
        assert set(auth.secret_values()) == {"key-1", "client-1"}


class TestKickscalePageNumberPaginator:
    @parameterized.expand(
        [
            ("full_page_keeps_going", 100, 100, True),
            ("short_page_is_terminal", 100, 40, False),
            ("empty_page_is_terminal", 100, 0, False),
        ]
    )
    def test_termination(self, _name: str, page_size: int, row_count: int, expected_has_next: bool) -> None:
        paginator = KickscalePageNumberPaginator(page_size=page_size)
        response = Mock()
        response.json.return_value = [{"id": str(i)} for i in range(row_count)]
        data = [{"id": str(i)} for i in range(row_count)]

        paginator.update_state(response, data=data)

        assert paginator.has_next_page is expected_has_next

    def test_page_param_advances_and_is_zero_based(self) -> None:
        paginator = KickscalePageNumberPaginator(page_size=100)
        request = Request(method="GET", url="https://api.kickscale.com/meetings")
        paginator.init_request(request)
        assert request.params["page"] == 0

        paginator.update_state(Mock(), data=[{"id": "1"}] * 100)
        paginator.update_request(request)
        assert request.params["page"] == 1

    def test_resume_state_round_trip(self) -> None:
        paginator = KickscalePageNumberPaginator(page_size=100)
        paginator.update_state(Mock(), data=[{"id": "1"}] * 100)
        state = paginator.get_resume_state()
        assert state == {"page": 1}

        resumed = KickscalePageNumberPaginator(page_size=100)
        resumed.set_resume_state(cast(dict[str, Any], state))
        request = Request(method="GET", url="https://api.kickscale.com/meetings")
        resumed.init_request(request)
        assert request.params["page"] == 1


@parameterized.expand(
    [
        ("naive_datetime", datetime(2026, 3, 1, 12, 30, 45, 999999), "2026-03-01T12:30:45Z"),
        ("aware_datetime", datetime(2026, 3, 1, 12, 30, 45, tzinfo=UTC), "2026-03-01T12:30:45Z"),
        ("passthrough_string", "1970-01-01T00:00:00Z", "1970-01-01T00:00:00Z"),
    ]
)
def test_format_kickscale_datetime(_name: str, value: Any, expected: str) -> None:
    assert _format_kickscale_datetime(value) == expected


class TestGetResource:
    @pytest.mark.parametrize("endpoint", ["meetings", "calls"])
    def test_incremental_resource(self, endpoint: str) -> None:
        resource = cast(dict[str, Any], get_resource(endpoint, should_use_incremental_field=True))
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        incremental = resource["endpoint"]["incremental"]
        assert incremental["start_param"] == "startDate"
        assert incremental["cursor_path"] == "date"

    @pytest.mark.parametrize("endpoint", ["meetings", "calls"])
    def test_full_refresh_resource(self, endpoint: str) -> None:
        resource = cast(dict[str, Any], get_resource(endpoint, should_use_incremental_field=False))
        assert resource["write_disposition"] == "replace"
        assert "incremental" not in resource["endpoint"]

    def test_requests_both_scopes_and_expand(self) -> None:
        resource = cast(dict[str, Any], get_resource("meetings", should_use_incremental_field=False))
        params = resource["endpoint"]["params"]
        # `scopes` defaults to "external" only; "internal" must be requested explicitly or
        # internal meetings silently drop out of every list response.
        assert params["scopes"] == "internal,external"
        assert params["expand"] == "user_client_augmentation,meeting_transcript"
        assert params["sortingOrder"] == "ascending"


def test_client_config_pins_host_and_blocks_redirects() -> None:
    # A redirect off the Kickscale host would otherwise replay the api-key/client-id headers.
    config = _client_config("key", "client")
    assert config["allowed_hosts"] == []
    assert config["allow_redirects"] is False


@parameterized.expand(
    [
        (200, True, None),
        (403, False, "Check both values"),
        (500, False, "unexpected status code"),
    ]
)
@patch("products.warehouse_sources.backend.temporal.data_imports.sources.kickscale.kickscale.make_tracked_session")
def test_validate_credentials_status_mapping(
    status: int, expected_valid: bool, message_fragment: str | None, mock_session: MagicMock
) -> None:
    mock_session.return_value.get.return_value = Mock(status_code=status)

    is_valid, message = validate_credentials("kickscale-key", "kickscale-client")

    assert is_valid is expected_valid
    if message_fragment is None:
        assert message is None
    else:
        assert message is not None and message_fragment in message

    call = mock_session.return_value.get.call_args
    assert call.args[0] == "https://api.kickscale.com/meetings"
    assert call.kwargs["headers"]["api-key"] == "kickscale-key"
    assert call.kwargs["headers"]["client-id"] == "kickscale-client"
    # The validation session must refuse redirects so a 3xx can't replay the credentials off-host.
    assert mock_session.call_args.kwargs["allow_redirects"] is False


def _make_http_response(body: list[dict[str, Any]], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestKickscaleSourceResumeBehavior:
    """End-to-end resume behaviour of ``kickscale_source`` via ``rest_api_resource``."""

    def _drive(
        self, endpoint: str, manager: MagicMock, responses: list[Response]
    ) -> tuple[MagicMock, list[dict[str, Any]]]:
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as mock_session_cls:
            mock_session = mock_session_cls.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            response = kickscale_source(
                api_key="test-key",
                client_id="test-client",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
            )
            list(cast(Iterable[Any], response.items()))
            return mock_session, sent_params

    @pytest.mark.parametrize("endpoint", ["meetings", "calls"])
    def test_fresh_run_pages_until_short_page(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response([{"id": f"m{i}"} for i in range(100)]),
            _make_http_response([{"id": "m100"}]),
        ]
        _, sent_params = self._drive(endpoint, manager, responses)

        pages_sent = [p.get("page") for p in sent_params]
        assert pages_sent == [0, 1]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [KickscaleResumeConfig(page=1)]

    def test_resume_seeds_paginator_with_saved_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = KickscaleResumeConfig(page=3)

        responses = [_make_http_response([{"id": "m1"}])]
        _, sent_params = self._drive("meetings", manager, responses)

        assert [p.get("page") for p in sent_params] == [3]
        manager.load_state.assert_called_once()

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response([{"id": "only"}])]
        self._drive("meetings", manager, responses)

        manager.save_state.assert_not_called()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response([{"id": "a"}])]
        self._drive("meetings", manager, responses)

        manager.load_state.assert_not_called()

    @pytest.mark.parametrize("endpoint", ["meetings", "calls"])
    def test_response_shape(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        responses = [_make_http_response([{"id": "1"}])]

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as mock_session_cls:
            mock_session = mock_session_cls.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            response_iter = iter(responses)
            mock_session.send.side_effect = lambda *_a, **_k: next(response_iter)

            response = kickscale_source(
                api_key="test-key",
                client_id="test-client",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
            )

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["date"]
        assert response.chunk_size == 1000
