import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.bigmailer import bigmailer
from products.warehouse_sources.backend.temporal.data_imports.sources.bigmailer.bigmailer import (
    AUTH_ERROR_MESSAGE,
    BigMailerAuthError,
    BigMailerResumeConfig,
    _build_url,
    _fetch_page,
    bigmailer_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


def _resp(status: int = 200, body: dict | None = None, text: str = "") -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.status_code = status
    response.ok = 200 <= status < 400
    response.json.return_value = body if body is not None else {}
    response.text = text

    def raise_for_status() -> None:
        if not response.ok:
            raise requests.HTTPError(f"{status} error", response=response)

    response.raise_for_status.side_effect = raise_for_status
    return response


class FakeManager(ResumableSourceManager[BigMailerResumeConfig]):
    """Stand-in for ResumableSourceManager: records saved state and replays a seeded resume state.

    Overrides every method `get_rows` touches, so the Redis-bound base `__init__` is skipped.
    """

    def __init__(self, state: BigMailerResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[BigMailerResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> BigMailerResumeConfig | None:
        return self._state

    def save_state(self, data: BigMailerResumeConfig) -> None:
        self.saved.append(data)


def _session_returning(*responses: MagicMock) -> MagicMock:
    session = MagicMock()
    session.get.side_effect = list(responses)
    return session


def _requested_urls(session: MagicMock) -> list[str]:
    return [call.args[0] for call in session.get.call_args_list]


class TestBuildUrl:
    def test_includes_limit_and_no_cursor(self) -> None:
        assert _build_url("/brands", None) == "https://api.bigmailer.io/v1/brands?limit=100"

    def test_cursor_is_percent_encoded(self) -> None:
        # BigMailer cursors are base64 and contain `==`; leaving them raw would corrupt the query string.
        url = _build_url("/brands/b1/contacts", "K5pwIGH3hgYrhytbDUY5eQ==")
        assert "cursor=K5pwIGH3hgYrhytbDUY5eQ%3D%3D" in url


class TestFetchPage:
    @parameterized.expand(
        [
            ("invalid_key_400", 400, '{"message":"Invalid api key"}'),
            ("unauthorized_401", 401, ""),
            ("forbidden_403", 403, ""),
        ]
    )
    def test_auth_failures_raise_non_retryable(self, _name: str, status: int, text: str) -> None:
        session = _session_returning(_resp(status=status, text=text))
        with pytest.raises(BigMailerAuthError) as exc:
            _fetch_page(session, "https://api.bigmailer.io/v1/brands?limit=100", MagicMock())
        assert str(exc.value) == AUTH_ERROR_MESSAGE

    def test_non_auth_400_raises_http_error_not_auth_error(self) -> None:
        # A 400 that isn't about the api key (e.g. a malformed param) must not be misreported as a
        # credential problem — otherwise a transient request bug would permanently disable the source.
        session = _session_returning(_resp(status=400, text='{"message":"bad cursor"}'))
        with pytest.raises(requests.HTTPError):
            _fetch_page(session, "https://api.bigmailer.io/v1/brands?limit=100", MagicMock())

    def test_404_raises_http_error(self) -> None:
        session = _session_returning(_resp(status=404, text="not found"))
        with pytest.raises(requests.HTTPError):
            _fetch_page(session, "https://api.bigmailer.io/v1/brands?limit=100", MagicMock())

    def test_200_returns_parsed_body(self) -> None:
        session = _session_returning(_resp(status=200, body={"data": [{"id": "x"}], "has_more": False}))
        assert _fetch_page(session, "https://api.bigmailer.io/v1/brands?limit=100", MagicMock()) == {
            "data": [{"id": "x"}],
            "has_more": False,
        }


def _run(endpoint: str, session: MagicMock, manager: FakeManager) -> list[dict]:
    with patch.object(bigmailer, "make_tracked_session", return_value=session):
        rows: list[dict] = []
        for page in get_rows(api_key="key", endpoint=endpoint, logger=MagicMock(), manager=manager):
            rows.extend(page)
        return rows


class TestTopLevelPagination:
    def test_follows_cursor_until_has_more_false(self) -> None:
        session = _session_returning(
            _resp(body={"data": [{"id": "b1", "created": 1}], "has_more": True, "cursor": "C2=="}),
            _resp(body={"data": [{"id": "b2", "created": 2}], "has_more": False, "cursor": "ignored"}),
        )
        rows = _run("brands", session, FakeManager())
        assert [r["id"] for r in rows] == ["b1", "b2"]
        # second request must carry the encoded cursor from page one
        assert "cursor=C2%3D%3D" in _requested_urls(session)[1]

    def test_does_not_inject_brand_id_for_top_level(self) -> None:
        session = _session_returning(_resp(body={"data": [{"id": "b1", "created": 1}], "has_more": False}))
        rows = _run("brands", session, FakeManager())
        assert "brand_id" not in rows[0]

    def test_saves_next_cursor_after_yielding_each_page(self) -> None:
        manager = FakeManager()
        session = _session_returning(
            _resp(body={"data": [{"id": "b1"}], "has_more": True, "cursor": "C2=="}),
            _resp(body={"data": [{"id": "b2"}], "has_more": False}),
        )
        _run("brands", session, manager)
        # one save (for the single page boundary that had a next page); none after the terminal page
        assert [(s.cursor, s.brand_id) for s in manager.saved] == [("C2==", None)]

    def test_resumes_from_saved_cursor(self) -> None:
        manager = FakeManager(BigMailerResumeConfig(cursor="RESUME==", brand_id=None))
        session = _session_returning(_resp(body={"data": [{"id": "b2"}], "has_more": False}))
        _run("brands", session, manager)
        assert "cursor=RESUME%3D%3D" in _requested_urls(session)[0]


class TestBrandFanOut:
    def test_iterates_every_brand_and_injects_brand_id(self) -> None:
        session = _session_returning(
            _resp(body={"data": [{"id": "b1"}, {"id": "b2"}], "has_more": False}),  # /brands
            _resp(body={"data": [{"id": "c1", "created": 1}], "has_more": False}),  # b1 contacts
            _resp(body={"data": [{"id": "c2", "created": 2}], "has_more": False}),  # b2 contacts
        )
        rows = _run("contacts", session, FakeManager())
        assert [(r["id"], r["brand_id"]) for r in rows] == [("c1", "b1"), ("c2", "b2")]

    def test_paginates_within_a_brand(self) -> None:
        session = _session_returning(
            _resp(body={"data": [{"id": "b1"}], "has_more": False}),  # /brands
            _resp(body={"data": [{"id": "c1"}], "has_more": True, "cursor": "P2=="}),  # b1 contacts page 1
            _resp(body={"data": [{"id": "c2"}], "has_more": False}),  # b1 contacts page 2
        )
        rows = _run("contacts", session, FakeManager())
        assert [r["id"] for r in rows] == ["c1", "c2"]
        assert "cursor=P2%3D%3D" in _requested_urls(session)[2]

    def test_resume_skips_already_processed_brands(self) -> None:
        # Resuming mid-fan-out must not re-request brands processed before the crash, and must start the
        # bookmarked brand from its saved cursor.
        manager = FakeManager(BigMailerResumeConfig(cursor="MID==", brand_id="b2"))
        session = _session_returning(
            _resp(body={"data": [{"id": "b1"}, {"id": "b2"}, {"id": "b3"}], "has_more": False}),  # /brands
            _resp(body={"data": [{"id": "c2"}], "has_more": False}),  # b2 contacts (resumed)
            _resp(body={"data": [{"id": "c3"}], "has_more": False}),  # b3 contacts (fresh)
        )
        rows = _run("contacts", session, manager)
        urls = _requested_urls(session)
        assert not any("/brands/b1/contacts" in u for u in urls)
        assert "/brands/b2/contacts" in urls[1] and "cursor=MID%3D%3D" in urls[1]
        assert "/brands/b3/contacts" in urls[2] and "cursor=" not in urls[2]
        assert [r["id"] for r in rows] == ["c2", "c3"]

    def test_advances_bookmark_between_brands(self) -> None:
        manager = FakeManager()
        session = _session_returning(
            _resp(body={"data": [{"id": "b1"}, {"id": "b2"}], "has_more": False}),
            _resp(body={"data": [{"id": "c1"}], "has_more": False}),
            _resp(body={"data": [{"id": "c2"}], "has_more": False}),
        )
        _run("contacts", session, manager)
        # after finishing b1 we bookmark b2 at its first page so a crash resumes on b2, not b1
        assert BigMailerResumeConfig(cursor=None, brand_id="b2") in manager.saved


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("invalid", 400, False), ("forbidden", 403, False)])
    def test_status_maps_to_bool(self, _name: str, status: int, expected: bool) -> None:
        session = _session_returning(_resp(status=status))
        with patch.object(bigmailer, "make_tracked_session", return_value=session):
            assert validate_credentials("key") is expected

    def test_network_error_is_false(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(bigmailer, "make_tracked_session", return_value=session):
            assert validate_credentials("key") is False


class TestSourceResponse:
    @parameterized.expand(
        [
            ("brands", ["id"]),
            ("users", ["id"]),
            ("contacts", ["brand_id", "id"]),
            ("bulk_campaigns", ["brand_id", "id"]),
            ("suppression_lists", ["brand_id", "id"]),
        ]
    )
    def test_primary_keys_per_endpoint(self, endpoint: str, expected_keys: list[str]) -> None:
        response = bigmailer_source(api_key="key", endpoint=endpoint, logger=MagicMock(), manager=MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == expected_keys

    def test_partitions_on_created_by_month(self) -> None:
        response = bigmailer_source(api_key="key", endpoint="contacts", logger=MagicMock(), manager=MagicMock())
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
        assert response.partition_keys == ["created"]
