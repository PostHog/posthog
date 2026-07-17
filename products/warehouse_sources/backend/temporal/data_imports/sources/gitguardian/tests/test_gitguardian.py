from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.gitguardian import gitguardian
from products.warehouse_sources.backend.temporal.data_imports.sources.gitguardian.gitguardian import (
    GitGuardianResumeConfig,
    check_endpoint_access,
    get_rows,
    gitguardian_source,
    resolve_base_url,
    validate_base_url,
    validate_credentials,
)

BASE_URL = "https://api.gitguardian.com"


def _page(rows: Any, next_url: str | None = None) -> MagicMock:
    response = MagicMock()
    response.json.return_value = rows
    response.links = {"next": {"url": next_url}} if next_url else {}
    return response


class _FakeManager:
    def __init__(self, state: GitGuardianResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[GitGuardianResumeConfig] = []
        self.cleared = False

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> GitGuardianResumeConfig | None:
        return self._state

    def save_state(self, data: GitGuardianResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.cleared = True


def _run_get_rows(
    monkeypatch: Any,
    endpoint: str,
    responses: list[MagicMock],
    manager: _FakeManager | None = None,
    **kwargs: Any,
) -> tuple[list[dict], list[str], _FakeManager]:
    fetched: list[str] = []
    resp_iter = iter(responses)

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> MagicMock:
        fetched.append(url)
        return next(resp_iter)

    monkeypatch.setattr(gitguardian, "_fetch_page", fake_fetch)
    monkeypatch.setattr(gitguardian, "make_tracked_session", lambda *a, **k: MagicMock())

    manager = manager or _FakeManager()
    rows: list[dict] = []
    for page in get_rows(
        api_key="gg_sat_x",
        base_url=BASE_URL,
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(page)
    return rows, fetched, manager


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


class TestResolveBaseUrl:
    @parameterized.expand(
        [
            ("blank", None, "https://api.gitguardian.com"),
            ("empty", "", "https://api.gitguardian.com"),
            ("trailing_slash", "https://api.eu1.gitguardian.com/", "https://api.eu1.gitguardian.com"),
            (
                "self_hosted_path_prefix",
                "https://gitguardian.acme.internal/exposed",
                "https://gitguardian.acme.internal/exposed",
            ),
        ]
    )
    def test_resolve(self, _name: str, given: str | None, expected: str) -> None:
        assert resolve_base_url(given) == expected


class TestValidateBaseUrl:
    @parameterized.expand(
        [
            ("default", "https://api.gitguardian.com"),
            ("self_hosted_https", "https://gitguardian.acme.dev"),
        ]
    )
    def test_https_urls_pass(self, _name: str, base_url: str) -> None:
        assert validate_base_url(base_url) is None

    @parameterized.expand(
        [
            # Plaintext would send the secret token in the clear.
            ("http", "http://gitguardian.acme.dev"),
            # `urlsplit` reads the host as example.com, but requests connects to 169.254.169.254.
            ("backslash_authority_confusion", "https://169.254.169.254\\@example.com"),
        ]
    )
    def test_unsafe_urls_are_rejected(self, _name: str, base_url: str) -> None:
        assert validate_base_url(base_url) is not None


class TestLinkHeaderPagination:
    def test_walks_pages_until_link_header_exhausted(self, monkeypatch: Any) -> None:
        # The next-page cursor lives in the Link header; the walk must follow it and stop when absent.
        next_url = f"{BASE_URL}/v1/incidents/secrets?cursor=abc&per_page=100&ordering=date"
        responses = [
            _page([{"id": 1}, {"id": 2}], next_url=next_url),
            _page([{"id": 3}]),
        ]
        rows, fetched, _ = _run_get_rows(monkeypatch, "secret_incidents", responses)
        assert [r["id"] for r in rows] == [1, 2, 3]
        assert fetched == [f"{BASE_URL}/v1/incidents/secrets?per_page=100&ordering=date", next_url]

    def test_first_sync_sends_ordering_but_no_date_filter(self, monkeypatch: Any) -> None:
        # No watermark => full backfill, but ordering must still be explicit so sort_mode="asc" holds.
        responses = [_page([{"id": 1}])]
        _, fetched, _ = _run_get_rows(
            monkeypatch,
            "secret_incidents",
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )
        query = _query(fetched[0])
        assert query["ordering"] == ["date"]
        assert "date_after" not in query

    def test_incremental_sends_date_after_with_lookback(self, monkeypatch: Any) -> None:
        # The watermark must reach the server as date_after (minus the safety lookback), otherwise
        # every "incremental" sync silently re-fetches all history.
        responses = [_page([{"id": 1}])]
        _, fetched, _ = _run_get_rows(
            monkeypatch,
            "secret_incidents",
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 10, tzinfo=UTC),
            incremental_field="date",
        )
        assert _query(fetched[0])["date_after"] == ["2026-01-03T00:00:00Z"]

    @parameterized.expand(
        [
            ("naive_datetime", datetime(2026, 1, 10), "2026-01-03T00:00:00Z"),
            ("date_value", date(2026, 1, 10), "2026-01-03T00:00:00Z"),
        ]
    )
    def test_incremental_value_types_are_formatted_utc(self, _name: str, value: Any, expected: str) -> None:
        responses = [_page([{"id": 1}])]
        with pytest.MonkeyPatch.context() as monkeypatch:
            _, fetched, _ = _run_get_rows(
                monkeypatch,
                "secret_incidents",
                responses,
                should_use_incremental_field=True,
                db_incremental_field_last_value=value,
            )
        assert _query(fetched[0])["date_after"] == [expected]

    def test_cross_origin_next_link_is_refused(self, monkeypatch: Any) -> None:
        # Pagination URLs are fetched with the Authorization token attached; a tampered Link
        # header must not be able to steer the token to another host.
        responses = [_page([{"id": 1}], next_url="https://attacker.example/v1/incidents/secrets?cursor=abc")]
        with pytest.raises(ValueError, match="cross-origin"):
            _run_get_rows(monkeypatch, "secret_incidents", responses)

    def test_non_list_response_raises_instead_of_yielding_garbage(self, monkeypatch: Any) -> None:
        responses = [_page({"detail": "Not found."})]
        with pytest.raises(ValueError, match="non-list response"):
            _run_get_rows(monkeypatch, "secret_incidents", responses)


class TestResumeCheckpoints:
    def test_resumes_from_saved_url(self, monkeypatch: Any) -> None:
        saved_url = f"{BASE_URL}/v1/incidents/secrets?cursor=abc&per_page=100"
        manager = _FakeManager(GitGuardianResumeConfig(url=saved_url))
        responses = [_page([{"id": 4}])]
        rows, fetched, _ = _run_get_rows(monkeypatch, "secret_incidents", responses, manager=manager)
        assert [r["id"] for r in rows] == [4]
        assert fetched == [saved_url]

    def test_cross_origin_resume_url_is_refused(self, monkeypatch: Any) -> None:
        # Resume URLs come from persisted state; a tampered value must not receive the token either.
        manager = _FakeManager(GitGuardianResumeConfig(url="https://attacker.example/v1/incidents/secrets?cursor=abc"))
        with pytest.raises(ValueError, match="cross-origin"):
            _run_get_rows(monkeypatch, "secret_incidents", [], manager=manager)

    def test_checkpoints_current_page_url_after_yield_and_clears_on_completion(self, monkeypatch: Any) -> None:
        # Resume must re-fetch the last yielded page (checkpoint the CURRENT URL, not the next one)
        # so a crash can't skip rows, and a finished walk must drop its checkpoint or a retry that
        # re-runs extract would resume from the final page and skip everything before it.
        next_url = f"{BASE_URL}/v1/incidents/secrets?cursor=abc&per_page=100"
        responses = [
            _page([{"id": 1}], next_url=next_url),
            _page([{"id": 2}]),
        ]
        _, fetched, manager = _run_get_rows(monkeypatch, "secret_incidents", responses)
        assert [s.url for s in manager.saved] == fetched
        assert manager.cleared is True

    def test_full_refresh_endpoints_never_checkpoint(self, monkeypatch: Any) -> None:
        # sources/members/teams merge nothing on resume, so a restart re-reads from page one.
        responses = [_page([{"id": 1}])]
        _, _, manager = _run_get_rows(monkeypatch, "sources", responses)
        assert manager.saved == []
        assert manager.cleared is False

    def test_full_refresh_endpoints_ignore_stale_resume_state(self, monkeypatch: Any) -> None:
        manager = _FakeManager(GitGuardianResumeConfig(url=f"{BASE_URL}/v1/sources?cursor=zzz"))
        responses = [_page([{"id": 1}])]
        _, fetched, _ = _run_get_rows(monkeypatch, "sources", responses, manager=manager)
        assert fetched == [f"{BASE_URL}/v1/sources?per_page=100"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_valid: bool) -> None:
        response = MagicMock()
        response.status_code = status_code
        session = MagicMock()
        session.get.return_value = response
        with patch.object(gitguardian, "make_tracked_session", return_value=session):
            valid, error = validate_credentials("gg_sat_x", BASE_URL)
        assert valid is expected_valid
        assert (error is None) is expected_valid

    def test_network_error_is_invalid_not_raised(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(gitguardian, "make_tracked_session", return_value=session):
            valid, error = validate_credentials("gg_sat_x", BASE_URL)
        assert valid is False
        assert error is not None


class TestCheckEndpointAccess:
    def _probe(self, response: MagicMock | Exception, endpoint: str = "secret_incidents") -> str | None:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        with patch.object(gitguardian, "make_tracked_session", return_value=session):
            return check_endpoint_access("gg_sat_x", BASE_URL, endpoint)

    def test_reachable_endpoint_reports_no_error(self) -> None:
        response = MagicMock()
        response.status_code = 200
        assert self._probe(response) is None

    def test_denial_surfaces_the_apis_own_detail_message(self) -> None:
        response = MagicMock()
        response.status_code = 403
        response.json.return_value = {"detail": "You do not have the required incidents:read scope."}
        assert self._probe(response) == "You do not have the required incidents:read scope."

    @parameterized.expand(
        [
            ("secret_incidents", "incidents:read"),
            ("sources", "sources:read"),
            ("honeytokens", "honeytokens:read"),
        ]
    )
    def test_denial_without_detail_names_the_required_scope(self, endpoint: str, scope: str) -> None:
        response = MagicMock()
        response.status_code = 403
        response.json.side_effect = ValueError("no json")
        reason = self._probe(response, endpoint=endpoint)
        assert reason is not None and scope in reason

    @parameterized.expand(
        [
            ("throttle", 429),
            ("server_error", 500),
        ]
    )
    def test_non_denial_errors_do_not_block_the_table(self, _name: str, status_code: int) -> None:
        # Only a real 401/403 is a missing scope; a throttle or blip must not mark the table
        # unreachable in the schema picker.
        response = MagicMock()
        response.status_code = status_code
        assert self._probe(response) is None

    def test_network_error_does_not_block_the_table(self) -> None:
        assert self._probe(requests.ConnectionError("boom")) is None


class TestFetchPageRetries:
    @parameterized.expand(
        [
            ("rate_limited", 429),
            ("server_error", 503),
        ]
    )
    def test_retryable_status_is_retried(self, _name: str, status_code: int) -> None:
        bad = MagicMock()
        bad.status_code = status_code
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        session = MagicMock()
        session.get.side_effect = [bad, good]

        with patch.object(gitguardian._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = gitguardian._fetch_page(session, f"{BASE_URL}/v1/incidents/secrets", {}, MagicMock())

        assert result is good
        assert session.get.call_count == 2

    def test_unauthorized_raises_and_is_not_retried(self) -> None:
        response = MagicMock()
        response.status_code = 401
        response.ok = False
        response.raise_for_status.side_effect = requests.HTTPError("401 Client Error: Unauthorized", response=response)
        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(requests.HTTPError):
            gitguardian._fetch_page(session, f"{BASE_URL}/v1/incidents/secrets", {}, MagicMock())
        assert session.get.call_count == 1


class TestSourceResponseShape:
    @parameterized.expand(
        [
            ("secret_incidents", ["date"]),
            ("secret_occurrences", ["date"]),
        ]
    )
    def test_incremental_endpoints_partition_on_stable_detection_date(
        self, endpoint: str, expected_partition: list[str]
    ) -> None:
        response = gitguardian_source(
            api_key="gg_sat_x",
            base_url=BASE_URL,
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.partition_keys == expected_partition
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"

    @parameterized.expand([("sources",), ("honeytokens",), ("members",), ("teams",)])
    def test_full_refresh_endpoints_are_unpartitioned(self, endpoint: str) -> None:
        response = gitguardian_source(
            api_key="gg_sat_x",
            base_url=BASE_URL,
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.partition_mode is None
        assert response.partition_keys is None
