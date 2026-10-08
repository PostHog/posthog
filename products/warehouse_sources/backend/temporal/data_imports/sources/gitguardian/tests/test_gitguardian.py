from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, NamedTuple
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


class _GetRowsResult(NamedTuple):
    rows: list[dict]
    fetched: list[str]
    manager: _FakeManager


def _run_get_rows(
    monkeypatch: Any,
    endpoint: str,
    responses: Sequence[MagicMock | Exception],
    manager: _FakeManager | None = None,
    **kwargs: Any,
) -> _GetRowsResult:
    fetched: list[str] = []
    resp_iter = iter(responses)

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> MagicMock:
        fetched.append(url)
        response = next(resp_iter)
        if isinstance(response, Exception):
            raise response
        return response

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
    return _GetRowsResult(rows, fetched, manager)


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
    def test_honeytoken_events_fetch_every_status(self, monkeypatch: Any) -> None:
        responses = [_page([]), _page([]), _page([])]
        _, fetched, _ = _run_get_rows(monkeypatch, "honeytoken_events", responses)
        assert [_query(url)["status"] for url in fetched] == [["open"], ["archived"], ["allowed"]]

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


def _http_error(status_code: int) -> requests.HTTPError:
    response = MagicMock()
    response.status_code = status_code
    return requests.HTTPError(f"{status_code} Client Error", response=response)


class TestFanOut:
    def test_walks_every_parent_page_and_each_childs_pages(self, monkeypatch: Any) -> None:
        teams_next = f"{BASE_URL}/v1/teams?cursor=t2&per_page=100"
        child_next = f"{BASE_URL}/v1/teams/1/team_memberships?cursor=m2&per_page=100"
        responses = [
            _page([{"id": 1}], next_url=teams_next),
            _page([{"id": 10, "team_id": 1}], next_url=child_next),
            _page([{"id": 11, "team_id": 1}]),
            _page([{"id": 2}]),
            _page([{"id": 20, "team_id": 2}]),
        ]
        rows, fetched, manager = _run_get_rows(monkeypatch, "team_memberships", responses)
        assert [r["id"] for r in rows] == [10, 11, 20]
        assert fetched == [
            f"{BASE_URL}/v1/teams?per_page=100",
            f"{BASE_URL}/v1/teams/1/team_memberships?per_page=100",
            child_next,
            teams_next,
            f"{BASE_URL}/v1/teams/2/team_memberships?per_page=100",
        ]
        assert manager.saved == []

    def test_parent_deleted_mid_sync_is_skipped(self, monkeypatch: Any) -> None:
        responses: Sequence[MagicMock | Exception] = [
            _page([{"id": 1}, {"id": 2}]),
            _http_error(404),
            _page([{"id": 20, "team_id": 2}]),
        ]
        rows, _, _ = _run_get_rows(monkeypatch, "team_memberships", responses)
        assert [r["id"] for r in rows] == [20]

    def test_child_denial_is_not_swallowed(self, monkeypatch: Any) -> None:
        responses: Sequence[MagicMock | Exception] = [_page([{"id": 1}]), _http_error(403)]
        with pytest.raises(requests.HTTPError):
            _run_get_rows(monkeypatch, "team_memberships", responses)


class TestResumeCheckpoints:
    def test_cross_origin_resume_url_is_refused(self, monkeypatch: Any) -> None:
        # Resume URLs come from persisted state; a tampered value must not receive the token either.
        manager = _FakeManager(GitGuardianResumeConfig(url="https://attacker.example/v1/incidents/secrets?cursor=abc"))
        with pytest.raises(ValueError, match="cross-origin"):
            _run_get_rows(monkeypatch, "secret_incidents", [], manager=manager)

    def test_full_refresh_endpoints_never_checkpoint(self, monkeypatch: Any) -> None:
        # sources/members/teams merge nothing on resume, so a restart re-reads from page one.
        responses = [_page([{"id": 1}])]
        _, _, manager = _run_get_rows(monkeypatch, "sources", responses)
        assert manager.saved == []
        assert manager.cleared is False


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

    @parameterized.expand(
        [
            ("team_memberships", "/v1/teams"),
            ("secret_incident_activity_logs", "/v1/incidents/secrets"),
        ]
    )
    def test_fan_out_endpoints_probe_their_parent(self, endpoint: str, parent_path: str) -> None:
        # The child path needs a real parent id; probing the placeholder would 404 and hide a
        # missing scope. The parent carries the same scope.
        response = MagicMock()
        response.status_code = 200
        session = MagicMock()
        session.get.return_value = response
        with patch.object(gitguardian, "make_tracked_session", return_value=session):
            check_endpoint_access("gg_sat_x", BASE_URL, endpoint)
        assert urlsplit(session.get.call_args.args[0]).path == parent_path


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
