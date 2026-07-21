from typing import Any, cast

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.rapid7_insightvm import rapid7_insightvm
from products.warehouse_sources.backend.temporal.data_imports.sources.rapid7_insightvm.rapid7_insightvm import (
    Rapid7InsightvmResumeConfig,
    get_rows,
    rapid7_insightvm_source,
    validate_credentials,
)

TRANSPORT = "products.warehouse_sources.backend.temporal.data_imports.sources.rapid7_insightvm.rapid7_insightvm"


class FakeManager:
    """In-memory stand-in for ResumableSourceManager that records saved cursors."""

    def __init__(self, initial: Rapid7InsightvmResumeConfig | None = None):
        self._state = initial
        self.saved: list[Rapid7InsightvmResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> Rapid7InsightvmResumeConfig | None:
        return self._state

    def save_state(self, data: Rapid7InsightvmResumeConfig) -> None:
        self.saved.append(data)
        self._state = data


def _response(status: int, body: dict[str, Any]) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status
    resp.ok = 200 <= status < 300
    resp.json.return_value = body
    resp.text = str(body)
    if not resp.ok:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status} error", response=resp)
    return resp


def _page(items: list[dict], cursor: str | None) -> dict[str, Any]:
    return {"data": items, "metadata": {"cursor": cursor} if cursor is not None else {}}


class TestGetRowsPagination:
    def _run(self, pages: list[dict], manager: FakeManager) -> tuple[list, mock.MagicMock]:
        session = mock.MagicMock()
        session.post.side_effect = [_response(200, page) for page in pages]
        with mock.patch(f"{TRANSPORT}.make_tracked_session", return_value=session):
            batches = list(
                get_rows(
                    api_key="key",
                    region="us",
                    endpoint="assets",
                    logger=mock.MagicMock(),
                    resumable_source_manager=cast(ResumableSourceManager[Rapid7InsightvmResumeConfig], manager),
                )
            )
        return batches, session

    def test_walks_pages_until_cursor_missing(self):
        pages = [
            _page([{"id": 1}], cursor="c1"),
            _page([{"id": 2}], cursor="c2"),
            _page([{"id": 3}], cursor=None),
        ]
        manager = FakeManager()
        batches, session = self._run(pages, manager)

        assert [item["id"] for batch in batches for item in batch] == [1, 2, 3]
        assert session.post.call_count == 3

    def test_terminates_when_cursor_repeats(self):
        # Some deployments echo the last cursor instead of dropping it; a naive loop would spin forever.
        pages = [_page([{"id": 1}], cursor="c1"), _page([{"id": 2}], cursor="c1")]
        manager = FakeManager()
        batches, session = self._run(pages, manager)

        assert [item["id"] for batch in batches for item in batch] == [1, 2]
        assert session.post.call_count == 2

    def test_terminates_on_empty_page(self):
        pages = [_page([], cursor="c1")]
        manager = FakeManager()
        batches, session = self._run(pages, manager)

        assert batches == []
        assert session.post.call_count == 1

    def test_saves_cursor_after_each_yielded_batch(self):
        pages = [
            _page([{"id": 1}], cursor="c1"),
            _page([{"id": 2}], cursor="c2"),
            _page([{"id": 3}], cursor=None),
        ]
        manager = FakeManager()
        self._run(pages, manager)

        # State is persisted only for pages that have a successor cursor (c1, c2); the final page
        # (no next cursor) saves nothing, so a resumed run re-yields the last page rather than skipping.
        assert [state.cursor for state in manager.saved] == ["c1", "c2"]

    def test_resumes_from_saved_cursor(self):
        pages = [_page([{"id": 99}], cursor=None)]
        manager = FakeManager(initial=Rapid7InsightvmResumeConfig(cursor="saved-cursor"))
        _, session = self._run(pages, manager)

        # The first (and only) request must carry the saved cursor as its starting point.
        first_call_url = session.post.call_args_list[0].args[0]
        assert "cursor=saved-cursor" in first_call_url


class TestFetchPageRetries:
    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_statuses_raise_retryable_error(self, status):
        session = mock.MagicMock()
        session.post.return_value = _response(status, {})
        with pytest.raises(rapid7_insightvm.Rapid7InsightvmRetryableError):
            rapid7_insightvm._fetch_page(
                session, "https://us.api.insight.rapid7.com/vm/v4/integration/assets", {}, {}, mock.MagicMock()
            )

    def test_client_error_raises_http_error(self):
        session = mock.MagicMock()
        session.post.return_value = _response(403, {})
        with pytest.raises(requests.HTTPError):
            rapid7_insightvm._fetch_page(
                session, "https://us.api.insight.rapid7.com/vm/v4/integration/assets", {}, {}, mock.MagicMock()
            )


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected_valid",
        [(200, True), (401, False), (403, False), (500, False)],
    )
    def test_status_maps_to_validity(self, status, expected_valid):
        session = mock.MagicMock()
        session.post.return_value = _response(status, {})
        with mock.patch(f"{TRANSPORT}.make_tracked_session", return_value=session):
            is_valid, message = validate_credentials("key", "us")

        assert is_valid is expected_valid
        assert (message is None) is expected_valid

    def test_network_error_is_not_valid(self):
        session = mock.MagicMock()
        session.post.side_effect = requests.ConnectionError("boom")
        with mock.patch(f"{TRANSPORT}.make_tracked_session", return_value=session):
            is_valid, message = validate_credentials("key", "us")

        assert is_valid is False
        assert message is not None


class TestCredentialedSessionIsHardened:
    # A 3xx from the credentialed Rapid7 endpoint would otherwise replay `X-Api-Key` to the
    # redirect target, so both entry points must pin redirects off and redact the key.
    def _get_rows(self) -> None:
        list(
            get_rows(
                api_key="secret-key",
                region="us",
                endpoint="assets",
                logger=mock.MagicMock(),
                resumable_source_manager=cast(ResumableSourceManager[Rapid7InsightvmResumeConfig], FakeManager()),
            )
        )

    def _validate(self) -> None:
        validate_credentials("secret-key", "us")

    @pytest.mark.parametrize("entry_point", ["_get_rows", "_validate"])
    def test_session_pins_redirects_off_and_redacts_key(self, entry_point):
        session = mock.MagicMock()
        session.post.return_value = _response(200, _page([], cursor=None))
        with mock.patch(f"{TRANSPORT}.make_tracked_session", return_value=session) as factory:
            getattr(self, entry_point)()

        factory.assert_called_once_with(redact_values=("secret-key",), allow_redirects=False)


class TestSourceResponse:
    @pytest.mark.parametrize("endpoint", ["assets", "vulnerabilities"])
    def test_full_refresh_endpoints_have_no_partitioning(self, endpoint):
        response = rapid7_insightvm_source(
            api_key="key",
            region="us",
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
