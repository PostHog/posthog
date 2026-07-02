from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.canny.canny import (
    PAGE_SIZE,
    CannyResumeConfig,
    CannyRetryableError,
    _build_body,
    _extract_records,
    _handle_response,
    canny_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.canny.settings import (
    CANNY_ENDPOINTS,
    ENDPOINTS,
    CannyEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

_POSTS = CANNY_ENDPOINTS["posts"]
_BOARDS = CANNY_ENDPOINTS["boards"]


def _resp(body: Any, status: int = 200) -> Any:
    response = MagicMock()
    response.status_code = status
    response.ok = 200 <= status < 400
    response.json.return_value = body
    response.text = str(body)
    return response


def _full_page(key: str) -> dict[str, Any]:
    return {key: [{"id": str(i)} for i in range(PAGE_SIZE)], "hasMore": True}


def _drive(
    endpoint: str, manager: Any, responses: list[Any]
) -> tuple[list[dict[str, Any]], list[list[dict[str, Any]]]]:
    """Drive ``get_rows`` with a mocked tracked session, returning (posted_bodies, yielded_batches)."""
    posted_bodies: list[dict[str, Any]] = []
    response_iter = iter(responses)

    def fake_post(url: str, data: Any = None, timeout: Any = None, **_kwargs: Any) -> Any:
        posted_bodies.append(dict(data or {}))
        return next(response_iter)

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.canny.canny.make_tracked_session"
    ) as MockSession:
        MockSession.return_value.post.side_effect = fake_post
        batches = list(get_rows(api_key="k", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=manager))

    return posted_bodies, batches


class TestBuildBody:
    def test_paginated_includes_skip_and_limit(self) -> None:
        assert _build_body("k", _POSTS, skip=200) == {"apiKey": "k", "skip": 200, "limit": PAGE_SIZE}

    def test_unpaginated_only_api_key(self) -> None:
        # boards/list takes no pagination params.
        assert _build_body("k", _BOARDS, skip=0) == {"apiKey": "k"}


class TestExtractRecords:
    def test_extracts_configured_key(self) -> None:
        config = CannyEndpointConfig(path="/v1/x/list", data_key="statusChanges")
        assert _extract_records({"statusChanges": [{"id": "1"}]}, config) == [{"id": "1"}]

    @pytest.mark.parametrize("body", [{}, {"posts": None}, {"posts": {"id": "1"}}, {"other": [{"id": "1"}]}])
    def test_missing_or_non_list_returns_empty(self, body: dict[str, Any]) -> None:
        assert _extract_records(body, _POSTS) == []


class TestHandleResponse:
    # Exercise the per-response classification directly, so a single attempt's behaviour can be
    # asserted without driving the tenacity retry loop (and its real backoff sleeps).
    def _handle(self, response: Any) -> dict[str, Any]:
        return _handle_response(response, "https://canny.io/api/v1/posts/list", MagicMock())

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_statuses_raise_retryable_error(self, status: int) -> None:
        with pytest.raises(CannyRetryableError):
            self._handle(_resp({}, status=status))

    @pytest.mark.parametrize("status", [400, 401, 403])
    def test_client_errors_raise_http_error(self, status: int) -> None:
        response = _resp({}, status=status)
        response.raise_for_status.side_effect = requests.HTTPError(f"{status} Client Error", response=response)
        with pytest.raises(requests.HTTPError):
            self._handle(response)

    def test_error_body_on_200_raises_http_error(self) -> None:
        # Canny can return 200 with an {"error": ...} body for a bad API key.
        with pytest.raises(requests.HTTPError, match="invalid API key"):
            self._handle(_resp({"error": "invalid API key"}))

    def test_success_returns_body(self) -> None:
        assert self._handle(_resp({"posts": [], "hasMore": False})) == {"posts": [], "hasMore": False}


class TestGetRows:
    def test_paginates_until_has_more_false_and_saves_after_each_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _full_page("posts"),
            _full_page("posts"),
            {"posts": [{"id": "final"}], "hasMore": False},
        ]
        posted, batches = _drive("posts", manager, [_resp(r) for r in responses])

        assert [b.get("skip") for b in posted] == [0, PAGE_SIZE, PAGE_SIZE * 2]
        assert len(batches) == 3
        # State is saved after each non-terminal page so a crash re-yields rather than skips.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [CannyResumeConfig(skip=PAGE_SIZE), CannyResumeConfig(skip=PAGE_SIZE * 2)]

    def test_resume_seeds_skip_from_saved_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = CannyResumeConfig(skip=PAGE_SIZE * 2)

        posted, batches = _drive("posts", manager, [_resp({"posts": [{"id": "x"}], "hasMore": False})])

        assert posted[0].get("skip") == PAGE_SIZE * 2
        manager.load_state.assert_called_once()
        assert len(batches) == 1

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        _, batches = _drive("posts", manager, [_resp({"posts": [{"id": "only"}], "hasMore": False})])

        assert len(batches) == 1
        manager.save_state.assert_not_called()

    def test_unpaginated_endpoint_fetches_once(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        # boards/list has no hasMore flag; a single fetch must terminate the loop.
        posted, batches = _drive("boards", manager, [_resp({"boards": [{"id": "b1"}]})])

        assert len(posted) == 1
        assert "skip" not in posted[0]
        assert batches == [[{"id": "b1"}]]
        manager.save_state.assert_not_called()

    def test_empty_page_yields_nothing(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        _, batches = _drive("posts", manager, [_resp({"posts": [], "hasMore": False})])

        assert batches == []
        manager.save_state.assert_not_called()

    def test_error_body_propagates(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        with pytest.raises(requests.HTTPError):
            _drive("posts", manager, [_resp({"error": "invalid API key"})])

    def test_registers_api_key_for_redaction(self) -> None:
        # The secret rides in the POST body through the tracked transport; it must be redacted so it
        # never lands in HTTP logs/samples.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.canny.canny.make_tracked_session"
        ) as MockSession:
            MockSession.return_value.post.return_value = _resp({"posts": [], "hasMore": False})
            list(get_rows(api_key="secret", endpoint="posts", logger=MagicMock(), resumable_source_manager=manager))

        MockSession.assert_called_once_with(redact_values=("secret",))


class TestValidateCredentials:
    def _validate(self, response: Any = None, raises: Exception | None = None) -> bool:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.canny.canny.make_tracked_session"
        ) as MockSession:
            post = MockSession.return_value.post
            if raises is not None:
                post.side_effect = raises
            else:
                post.return_value = response
            return validate_credentials("k")

    def test_valid_key(self) -> None:
        assert self._validate(_resp({"boards": []})) is True

    def test_error_body_is_invalid(self) -> None:
        assert self._validate(_resp({"error": "invalid API key"})) is False

    def test_non_ok_is_invalid(self) -> None:
        assert self._validate(_resp({}, status=401)) is False

    def test_network_error_is_invalid(self) -> None:
        assert self._validate(raises=requests.ConnectionError("boom")) is False

    def test_registers_api_key_for_redaction(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.canny.canny.make_tracked_session"
        ) as MockSession:
            MockSession.return_value.post.return_value = _resp({"boards": []})
            validate_credentials("secret")

        MockSession.assert_called_once_with(redact_values=("secret",))


class TestCannySource:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_response_shape(self, endpoint: str) -> None:
        response = canny_source(
            api_key="k", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=MagicMock()
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Every Canny object carries a stable `created` timestamp we partition on.
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created"]
