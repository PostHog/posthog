import base64
from typing import Any, cast

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.dropbox_sign import dropbox_sign
from products.warehouse_sources.backend.temporal.data_imports.sources.dropbox_sign.dropbox_sign import (
    DROPBOX_SIGN_BASE_URL,
    DropboxSignResumeConfig,
    _get_headers,
    dropbox_sign_source,
    get_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dropbox_sign.settings import (
    DROPBOX_SIGN_ENDPOINTS,
    ENDPOINTS,
)


class TestGetHeaders:
    def test_uses_http_basic_with_blank_password(self) -> None:
        headers = _get_headers("my-key")
        expected = base64.b64encode(b"my-key:").decode("ascii")
        assert headers["Authorization"] == f"Basic {expected}"
        assert headers["Accept"] == "application/json"


class _FakeResumableManager:
    def __init__(self, state: DropboxSignResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[DropboxSignResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> DropboxSignResumeConfig | None:
        return self._state

    def save_state(self, data: DropboxSignResumeConfig) -> None:
        self.saved.append(data)


def _page_body(data_key: str, items: list[dict], page: int, num_pages: int) -> dict:
    return {
        "list_info": {"page": page, "num_pages": num_pages, "num_results": 0, "page_size": 100},
        data_key: items,
    }


class TestGetRows:
    @staticmethod
    def _collect(
        endpoint: str,
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages_by_page_number: dict[int, dict],
    ) -> tuple[list[dict], list[dict[str, Any]]]:
        """Drive ``get_rows`` with ``_fetch_page`` faked to serve responses by requested page."""
        sent_params: list[dict[str, Any]] = []

        def fake_fetch(session: Any, url: str, headers: dict[str, str], params: dict[str, Any], logger: Any) -> dict:
            sent_params.append(dict(params))
            page = params.get("page", 1)
            return pages_by_page_number[page]

        monkeypatch.setattr(dropbox_sign, "_fetch_page", fake_fetch)

        rows: list[dict] = []
        for table in get_rows(
            api_key="key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(table.to_pylist())
        return rows, sent_params

    def test_single_page_yields_all_rows(self, monkeypatch: Any) -> None:
        pages = {1: _page_body("signature_requests", [{"signature_request_id": "a"}], page=1, num_pages=1)}
        rows, sent = self._collect("signature_requests", _FakeResumableManager(), monkeypatch, pages)
        assert rows == [{"signature_request_id": "a"}]
        assert sent == [{"page": 1, "page_size": 100}]

    def test_walks_every_page(self, monkeypatch: Any) -> None:
        pages = {
            1: _page_body("templates", [{"template_id": "t1"}], page=1, num_pages=3),
            2: _page_body("templates", [{"template_id": "t2"}], page=2, num_pages=3),
            3: _page_body("templates", [{"template_id": "t3"}], page=3, num_pages=3),
        }
        rows, sent = self._collect("templates", _FakeResumableManager(), monkeypatch, pages)
        assert [r["template_id"] for r in rows] == ["t1", "t2", "t3"]
        assert [p["page"] for p in sent] == [1, 2, 3]

    def test_stops_when_page_has_no_items(self, monkeypatch: Any) -> None:
        # A page claiming more pages but returning no items must still terminate (defensive).
        pages = {1: _page_body("templates", [], page=1, num_pages=5)}
        rows, sent = self._collect("templates", _FakeResumableManager(), monkeypatch, pages)
        assert rows == []
        assert [p["page"] for p in sent] == [1]

    def test_resume_starts_from_saved_page(self, monkeypatch: Any) -> None:
        pages = {
            2: _page_body("templates", [{"template_id": "t2"}], page=2, num_pages=2),
        }
        manager = _FakeResumableManager(DropboxSignResumeConfig(page=2))
        rows, sent = self._collect("templates", manager, monkeypatch, pages)
        assert [r["template_id"] for r in rows] == ["t2"]
        assert [p["page"] for p in sent] == [2]

    def test_does_not_load_state_when_cannot_resume(self, monkeypatch: Any) -> None:
        pages = {1: _page_body("templates", [{"template_id": "t1"}], page=1, num_pages=1)}
        manager = _FakeResumableManager()
        load_spy = MagicMock(side_effect=manager.load_state)
        monkeypatch.setattr(manager, "load_state", load_spy)
        self._collect("templates", manager, monkeypatch, pages)
        load_spy.assert_not_called()

    def test_api_apps_oauth_secret_is_redacted(self, monkeypatch: Any) -> None:
        # The API App List response nests the OAuth client secret; it must never reach the warehouse.
        item = {"client_id": "c1", "oauth": {"callback_url": "https://x/cb", "secret": "sk_live_super_secret"}}
        pages = {1: _page_body("api_apps", [item], page=1, num_pages=1)}
        rows, _ = self._collect("api_apps", _FakeResumableManager(), monkeypatch, pages)
        # The pipeline JSON-serializes nested objects into a string column, so assert on the
        # serialized payload rather than a nested dict: the secret (key and value) must be gone,
        # while the rest of the record survives.
        assert rows[0]["client_id"] == "c1"
        assert "secret" not in rows[0]["oauth"]
        assert "sk_live_super_secret" not in rows[0]["oauth"]
        assert "callback_url" in rows[0]["oauth"]

    def test_signature_requests_signing_url_is_redacted(self, monkeypatch: Any) -> None:
        # Incomplete signature requests expose a `signing_url` bearer link; it must never reach the warehouse.
        item = {"signature_request_id": "sr1", "signing_url": "https://app.hellosign.com/sign/abc", "title": "Doc"}
        pages = {1: _page_body("signature_requests", [item], page=1, num_pages=1)}
        rows, _ = self._collect("signature_requests", _FakeResumableManager(), monkeypatch, pages)
        assert rows[0]["signature_request_id"] == "sr1"
        assert "signing_url" not in rows[0]
        assert rows[0]["title"] == "Doc"

    def test_single_object_endpoint_yields_one_row_without_pagination(self, monkeypatch: Any) -> None:
        captured: list[dict[str, Any]] = []

        def fake_fetch(session: Any, url: str, headers: dict[str, str], params: dict[str, Any], logger: Any) -> dict:
            captured.append(dict(params))
            return {"account": {"account_id": "acc_1", "email_address": "a@b.com"}}

        monkeypatch.setattr(dropbox_sign, "_fetch_page", fake_fetch)

        rows: list[dict] = []
        for table in get_rows(
            api_key="key",
            endpoint="account",
            logger=MagicMock(),
            resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
        ):
            rows.extend(table.to_pylist())

        assert rows == [{"account_id": "acc_1", "email_address": "a@b.com"}]
        # Single-object endpoints send no pagination params.
        assert captured == [{}]


class TestResumeStateSaving:
    """The resume page is saved AFTER a batch is yielded, and only while a later page remains."""

    def _drive_with_small_chunks(self, monkeypatch: Any, num_pages: int, items_per_page: int) -> _FakeResumableManager:
        manager = _FakeResumableManager()

        # Force a yield after every page by shrinking the batcher chunk size to the page size.
        real_batcher_cls = dropbox_sign.Batcher

        def small_batcher(*_args: Any, **kwargs: Any) -> Any:
            kwargs["chunk_size"] = items_per_page
            return real_batcher_cls(*_args, **kwargs)

        monkeypatch.setattr(dropbox_sign, "Batcher", small_batcher)

        def fake_fetch(session: Any, url: str, headers: dict[str, str], params: dict[str, Any], logger: Any) -> dict:
            page = params.get("page", 1)
            items = [{"signature_request_id": f"p{page}-{i}"} for i in range(items_per_page)]
            return _page_body("signature_requests", items, page=page, num_pages=num_pages)

        monkeypatch.setattr(dropbox_sign, "_fetch_page", fake_fetch)

        for _table in get_rows(
            api_key="key",
            endpoint="signature_requests",
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            pass
        return manager

    def test_saves_each_non_terminal_page(self, monkeypatch: Any) -> None:
        manager = self._drive_with_small_chunks(monkeypatch, num_pages=3, items_per_page=2)
        # Pages 1 and 2 are non-terminal (a later page remains); page 3 is terminal and not saved.
        assert manager.saved == [DropboxSignResumeConfig(page=1), DropboxSignResumeConfig(page=2)]

    def test_single_page_saves_nothing(self, monkeypatch: Any) -> None:
        manager = self._drive_with_small_chunks(monkeypatch, num_pages=1, items_per_page=2)
        assert manager.saved == []


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,expected",
        [(200, True), (401, False), (403, False), (500, False)],
    )
    def test_status_maps_to_bool(self, monkeypatch: Any, status_code: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status_code
        session = MagicMock()
        session.get.return_value = response
        monkeypatch.setattr(dropbox_sign, "make_tracked_session", lambda *a, _s=session, **k: _s)

        assert dropbox_sign.validate_credentials("key") is expected, status_code

    def test_network_error_returns_false(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        monkeypatch.setattr(dropbox_sign, "make_tracked_session", lambda *a, **k: session)

        assert dropbox_sign.validate_credentials("key") is False


class TestSourceResponse:
    @parameterized.expand(list(ENDPOINTS))
    def test_primary_keys_match_settings(self, endpoint: str) -> None:
        response = dropbox_sign_source(
            api_key="key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == DROPBOX_SIGN_ENDPOINTS[endpoint].primary_keys

    @parameterized.expand(
        [
            ("signature_requests", True),
            ("api_apps", True),
            ("templates", False),
            ("account", False),
        ]
    )
    def test_partitioning_only_when_endpoint_has_partition_key(self, endpoint: str, partitioned: bool) -> None:
        response = dropbox_sign_source(
            api_key="key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        if partitioned:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["created_at"]
            assert response.partition_format == "month"
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_base_url_is_v3(self) -> None:
        assert DROPBOX_SIGN_BASE_URL == "https://api.hellosign.com/v3"


class TestRetryClassification:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status_code: int) -> None:
        response = MagicMock()
        response.status_code = status_code
        response.ok = False
        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(dropbox_sign.DropboxSignRetryableError):
            # Call the undecorated function body once via the public wrapper with a single attempt
            # would still retry; instead assert the classification directly.
            cast(Any, dropbox_sign._fetch_page).__wrapped__(session, "http://x", {}, {}, MagicMock())

    def test_client_error_raises_http_error(self) -> None:
        response = MagicMock()
        response.status_code = 400
        response.ok = False
        response.raise_for_status.side_effect = requests.HTTPError("400", response=cast(requests.Response, response))
        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(requests.HTTPError):
            cast(Any, dropbox_sign._fetch_page).__wrapped__(session, "http://x", {}, {}, MagicMock())
