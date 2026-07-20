import json
from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.sonatype_nexus.settings import (
    ENDPOINTS,
    SONATYPE_NEXUS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sonatype_nexus.sonatype_nexus import (
    SonatypeNexusPaginationError,
    SonatypeNexusResponseTimeoutError,
    SonatypeNexusResponseTooLargeError,
    SonatypeNexusResumeConfig,
    SonatypeNexusRetryableError,
    _build_url,
    _fetch_page,
    _read_bounded,
    get_rows,
    hostname_of,
    normalize_host,
    sonatype_nexus_source,
    validate_credentials,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.sonatype_nexus.sonatype_nexus"

# `_fetch_page` is wrapped by tenacity's @retry; call the underlying function directly so a
# retryable status raises immediately instead of sleeping through the backoff schedule.
_fetch_undecorated = _fetch_page.__wrapped__  # type: ignore[attr-defined]

_REPOSITORIES = [
    {"name": "maven-releases", "format": "maven2", "type": "hosted"},
    {"name": "maven-public", "format": "maven2", "type": "group"},
    {"name": "docker-proxy", "format": "docker", "type": "proxy"},
]


def _make_manager(resume_state: SonatypeNexusResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(body: Any, status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    # Bodies are streamed and read through iter_content + json.loads, never .json(), and
    # `_fetch_page` reads the response inside a `with` block.
    payload = json.dumps(body).encode()
    resp.iter_content = mock.Mock(side_effect=lambda chunk_size: iter([payload]))
    resp.__enter__ = mock.Mock(return_value=resp)
    resp.__exit__ = mock.Mock(return_value=False)
    return resp


def _streaming_response(chunks: list[bytes], status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.iter_content = mock.Mock(side_effect=lambda chunk_size: iter(chunks))
    resp.__enter__ = mock.Mock(return_value=resp)
    resp.__exit__ = mock.Mock(return_value=False)
    return resp


def _not_found_response() -> mock.MagicMock:
    resp = _response({}, status_code=404)
    resp.raise_for_status.side_effect = requests.HTTPError("404 Client Error", response=resp)
    return resp


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("https://nexus.example.com", "https://nexus.example.com"),
            ("nexus.example.com", "https://nexus.example.com"),
            ("https://nexus.example.com/", "https://nexus.example.com"),
            ("http://nexus.internal:8081", "http://nexus.internal:8081"),
            # A pasted API base URL is tolerated by trimming the REST path suffix.
            ("https://nexus.example.com/service/rest/v1", "https://nexus.example.com"),
            ("https://nexus.example.com/service/rest/v1/", "https://nexus.example.com"),
            ("https://nexus.example.com/service/rest", "https://nexus.example.com"),
        ],
    )
    def test_valid_hosts(self, value, expected):
        assert normalize_host(value) == expected

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "   ",
            "ftp://example.com",
            "https://",
            # SSRF: urlparse reads the host as example.com but urllib3 connects to
            # 127.0.0.1 (backslash / userinfo confusion), so these must be rejected.
            r"http://127.0.0.1\@example.com",
            r"http://127.0.0.1%5c@example.com",
            "https://user@127.0.0.1",
        ],
    )
    def test_invalid_hosts_raise(self, value):
        with pytest.raises(ValueError):
            normalize_host(value)

    @pytest.mark.parametrize(
        "cloud, host, expect_raise",
        [
            # On cloud the credentials would egress over the public internet, so
            # plaintext http is rejected while https is fine.
            (True, "http://nexus.example.com", True),
            (True, "https://nexus.example.com", False),
            # Self-hosted operators control their network path, so http stays allowed.
            (False, "http://nexus.internal:8081", False),
        ],
    )
    def test_http_requires_https_only_on_cloud(self, cloud, host, expect_raise):
        with mock.patch(f"{_MODULE}.is_cloud", return_value=cloud):
            if expect_raise:
                with pytest.raises(ValueError):
                    normalize_host(host)
            else:
                assert normalize_host(host) == host

    def test_hostname_of(self):
        assert hostname_of("https://nexus.example.com/service/rest/v1") == "nexus.example.com"


class TestFetchPage:
    @pytest.mark.parametrize("status_code", [429, 500, 502, 503])
    def test_retryable_statuses_raise_retryable_error(self, status_code):
        session = mock.MagicMock()
        session.get.return_value = _response({}, status_code=status_code)
        with pytest.raises(SonatypeNexusRetryableError):
            _fetch_undecorated(session, "https://x", mock.MagicMock())

    @pytest.mark.parametrize("status_code", [400, 401, 403, 404])
    def test_client_errors_raise_for_status(self, status_code):
        session = mock.MagicMock()
        resp = _response({}, status_code=status_code)
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code} Client Error", response=resp)
        session.get.return_value = resp
        with pytest.raises(requests.HTTPError):
            _fetch_undecorated(session, "https://x", mock.MagicMock())

    def test_list_body_is_wrapped_in_items(self):
        # /repositories returns a plain JSON array instead of the paginated envelope.
        session = mock.MagicMock()
        session.get.return_value = _response([{"name": "maven-releases"}])
        body = _fetch_undecorated(session, "https://x", mock.MagicMock())
        assert body == {"items": [{"name": "maven-releases"}]}


class TestReadBounded:
    def test_oversized_body_aborts_instead_of_buffering(self):
        resp = _streaming_response([b"x" * 10, b"x" * 10])
        with pytest.raises(SonatypeNexusResponseTooLargeError):
            _read_bounded(resp, max_bytes=15)

    def test_slow_drip_body_aborts_on_total_deadline(self):
        # A body that stays under the per-read timeout but never finishes is aborted once the
        # total-transfer deadline passes, rather than holding the worker indefinitely.
        resp = _streaming_response([b"x", b"x"])
        with mock.patch(f"{_MODULE}.time.monotonic", side_effect=[0.0, 601.0]):
            with pytest.raises(SonatypeNexusResponseTimeoutError):
                _read_bounded(resp, max_bytes=1_000_000, max_seconds=600)


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_valid_credentials(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        assert validate_credentials("https://nexus.example.com", "user", "pass") is True
        assert mock_session.return_value.auth == ("user", "pass")
        url = mock_session.return_value.get.call_args.args[0]
        assert url == "https://nexus.example.com/service/rest/v1/repositories"

    @pytest.mark.parametrize("status_code", [401, 403, 500])
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_non_200_fails_validation(self, mock_session, status_code):
        mock_session.return_value.get.return_value = _response({}, status_code=status_code)
        assert validate_credentials("https://nexus.example.com", "user", "bad") is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_network_error_fails_validation(self, mock_session):
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("https://nexus.example.com", "user", "pass") is False


class TestGetRowsTopLevel:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_repositories_single_fetch_yields_and_stops(self, mock_session):
        mock_session.return_value.get.return_value = _response(_REPOSITORIES)

        manager = _make_manager()
        batches = list(get_rows("https://n.example.com", "u", "p", "repositories", mock.MagicMock(), manager))

        assert batches == [_REPOSITORIES]
        manager.save_state.assert_not_called()
        assert mock_session.return_value.get.call_count == 1
        url = mock_session.return_value.get.call_args.args[0]
        assert url == "https://n.example.com/service/rest/v1/repositories"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_tasks_paginates_and_saves_token_after_each_page(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"items": [{"id": "1"}], "continuationToken": "TOKEN_A"}),
            _response({"items": [{"id": "2"}], "continuationToken": "TOKEN_B"}),
            _response({"items": [{"id": "3"}], "continuationToken": None}),
        ]

        manager = _make_manager()
        batches = list(get_rows("https://n.example.com", "u", "p", "tasks", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["1", "2", "3"]
        # State saved once per page that has a following page (not for the last page).
        saved = [call.args[0].continuation_token for call in manager.save_state.call_args_list]
        assert saved == ["TOKEN_A", "TOKEN_B"]
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert "continuationToken=TOKEN_A" in second_url

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_tasks_resumes_from_saved_token(self, mock_session):
        mock_session.return_value.get.return_value = _response({"items": [{"id": "9"}], "continuationToken": None})

        manager = _make_manager(SonatypeNexusResumeConfig(continuation_token="SAVED"))
        list(get_rows("https://n.example.com", "u", "p", "tasks", mock.MagicMock(), manager))

        first_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert "continuationToken=SAVED" in first_url

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_tasks_empty_page_still_terminates(self, mock_session):
        mock_session.return_value.get.return_value = _response({"items": [], "continuationToken": None})

        manager = _make_manager()
        batches = list(get_rows("https://n.example.com", "u", "p", "tasks", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_non_advancing_token_raises(self, mock_session):
        # A server that keeps returning the same token would loop forever; it must fail instead.
        mock_session.return_value.get.return_value = _response({"items": [{"id": "1"}], "continuationToken": "STUCK"})

        manager = _make_manager()
        with pytest.raises(SonatypeNexusPaginationError):
            list(get_rows("https://n.example.com", "u", "p", "tasks", mock.MagicMock(), manager))

    @mock.patch(f"{_MODULE}.MAX_PAGES_PER_ENDPOINT", 2)
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_page_ceiling_raises(self, mock_session):
        # A server that hands out fresh tokens forever is bounded by the page ceiling.
        mock_session.return_value.get.side_effect = [
            _response({"items": [{"id": "1"}], "continuationToken": "A"}),
            _response({"items": [{"id": "2"}], "continuationToken": "B"}),
            _response({"items": [{"id": "3"}], "continuationToken": "C"}),
        ]

        manager = _make_manager()
        with pytest.raises(SonatypeNexusPaginationError):
            list(get_rows("https://n.example.com", "u", "p", "tasks", mock.MagicMock(), manager))

    @mock.patch(f"{_MODULE}.MAX_PAGINATION_SECONDS", -1)
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_pagination_time_budget_raises(self, mock_session):
        # Individually valid pages with fresh tokens must still fail once the cumulative
        # wall-clock budget is exhausted, so a slow-drip host can't run until the activity timeout.
        mock_session.return_value.get.side_effect = [
            _response({"items": [{"id": "1"}], "continuationToken": "A"}),
            _response({"items": [{"id": "2"}], "continuationToken": "B"}),
        ]

        manager = _make_manager()
        with pytest.raises(SonatypeNexusPaginationError):
            list(get_rows("https://n.example.com", "u", "p", "tasks", mock.MagicMock(), manager))


class TestGetRowsRepositoryFanout:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_fans_out_over_non_group_repositories(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response(_REPOSITORIES),
            _response({"items": [{"id": "d1", "repository": "docker-proxy"}], "continuationToken": None}),
            _response({"items": [{"id": "m1", "repository": "maven-releases"}], "continuationToken": None}),
        ]

        manager = _make_manager()
        batches = list(get_rows("https://n.example.com", "u", "p", "components", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["d1", "m1"]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        # Repositories are walked sorted by name; group repositories are excluded
        # because they'd double-count their members' components.
        assert "repository=docker-proxy" in urls[1]
        assert "repository=maven-releases" in urls[2]
        assert not any("maven-public" in url for url in urls)
        # The bookmark advances to the next repository after each one completes.
        saved = [(c.args[0].repository, c.args[0].continuation_token) for c in manager.save_state.call_args_list]
        assert saved == [("maven-releases", None)]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_saves_repository_and_token_after_each_page(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response(_REPOSITORIES),
            _response({"items": [{"id": "d1"}], "continuationToken": "TOKEN_A"}),
            _response({"items": [{"id": "d2"}], "continuationToken": None}),
            _response({"items": [{"id": "m1"}], "continuationToken": None}),
        ]

        manager = _make_manager()
        batches = list(get_rows("https://n.example.com", "u", "p", "assets", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["d1", "d2", "m1"]
        third_url = mock_session.return_value.get.call_args_list[2].args[0]
        assert "repository=docker-proxy" in third_url
        assert "continuationToken=TOKEN_A" in third_url
        saved = [(c.args[0].repository, c.args[0].continuation_token) for c in manager.save_state.call_args_list]
        assert saved == [("docker-proxy", "TOKEN_A"), ("maven-releases", None)]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_page_with_token_still_checkpoints(self, mock_session):
        # An empty page that still returns a continuation token must save state, so a crash
        # resumes from the page's real progression rather than an older token.
        mock_session.return_value.get.side_effect = [
            _response(_REPOSITORIES),
            _response({"items": [], "continuationToken": "TOKEN_A"}),
            _response({"items": [{"id": "d1"}], "continuationToken": None}),
            _response({"items": [{"id": "m1"}], "continuationToken": None}),
        ]

        manager = _make_manager()
        batches = list(get_rows("https://n.example.com", "u", "p", "components", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["d1", "m1"]
        saved = [(c.args[0].repository, c.args[0].continuation_token) for c in manager.save_state.call_args_list]
        assert saved == [("docker-proxy", "TOKEN_A"), ("maven-releases", None)]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_bookmarked_repository_and_token(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response(_REPOSITORIES),
            _response({"items": [{"id": "m1"}], "continuationToken": None}),
        ]

        manager = _make_manager(SonatypeNexusResumeConfig(continuation_token="SAVED", repository="maven-releases"))
        batches = list(get_rows("https://n.example.com", "u", "p", "components", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["m1"]
        # docker-proxy sorts before the bookmark, so it is skipped entirely.
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert len(urls) == 2
        assert "repository=maven-releases" in urls[1]
        assert "continuationToken=SAVED" in urls[1]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resume_with_deleted_bookmark_repository_starts_over(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response(_REPOSITORIES),
            _response({"items": [{"id": "d1"}], "continuationToken": None}),
            _response({"items": [{"id": "m1"}], "continuationToken": None}),
        ]

        manager = _make_manager(SonatypeNexusResumeConfig(continuation_token="SAVED", repository="deleted-repo"))
        batches = list(get_rows("https://n.example.com", "u", "p", "components", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["d1", "m1"]
        # The saved token belongs to the deleted repository and must not leak into
        # the fresh walk.
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert not any("continuationToken=SAVED" in url for url in urls)

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_repository_deleted_mid_sync_is_skipped(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response(_REPOSITORIES),
            _not_found_response(),
            _response({"items": [{"id": "m1"}], "continuationToken": None}),
        ]

        manager = _make_manager()
        batches = list(get_rows("https://n.example.com", "u", "p", "components", mock.MagicMock(), manager))

        # docker-proxy 404s (deleted between enumeration and fetch) and is skipped;
        # maven-releases still syncs.
        assert [row["id"] for batch in batches for row in batch] == ["m1"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_non_advancing_token_raises(self, mock_session):
        # A repository whose pages never advance the token must fail rather than loop forever.
        mock_session.return_value.get.side_effect = [
            _response(_REPOSITORIES),
            _response({"items": [{"id": "d1"}], "continuationToken": "STUCK"}),
            _response({"items": [{"id": "d2"}], "continuationToken": "STUCK"}),
        ]

        manager = _make_manager()
        with pytest.raises(SonatypeNexusPaginationError):
            list(get_rows("https://n.example.com", "u", "p", "components", mock.MagicMock(), manager))

    @mock.patch(f"{_MODULE}.MAX_PAGINATION_SECONDS", -1)
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_pagination_time_budget_raises(self, mock_session):
        # A per-repository walk of individually valid small pages must fail once the cumulative
        # wall-clock budget is exhausted, independent of the per-response transfer deadline.
        mock_session.return_value.get.side_effect = [
            _response(_REPOSITORIES),
            _response({"items": [{"id": "d1"}], "continuationToken": "A"}),
            _response({"items": [{"id": "d2"}], "continuationToken": "B"}),
        ]

        manager = _make_manager()
        with pytest.raises(SonatypeNexusPaginationError):
            list(get_rows("https://n.example.com", "u", "p", "components", mock.MagicMock(), manager))

    @mock.patch(f"{_MODULE}.MAX_PAGINATION_SECONDS", -1)
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_pagination_time_budget_raises_on_terminal_pages(self, mock_session):
        # A host that slow-drips a single terminal page (no continuation token) per repository
        # must still trip the cumulative deadline — the check runs after every response, not only
        # before continuing to a next page, so terminal pages can't bypass it across many repos.
        mock_session.return_value.get.side_effect = [
            _response(_REPOSITORIES),
            _response({"items": [{"id": "d1"}], "continuationToken": None}),
            _response({"items": [{"id": "m1"}], "continuationToken": None}),
        ]

        manager = _make_manager()
        with pytest.raises(SonatypeNexusPaginationError):
            list(get_rows("https://n.example.com", "u", "p", "components", mock.MagicMock(), manager))


class TestSonatypeNexusSource:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_response_primary_keys_and_no_partitioning(self, endpoint):
        config = SONATYPE_NEXUS_ENDPOINTS[endpoint]
        response = sonatype_nexus_source("https://n.example.com", "u", "p", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # No Nexus endpoint has a universally-populated stable timestamp, so
        # nothing is datetime-partitioned.
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_build_url_encodes_params(self):
        url = _build_url("https://x/service/rest/v1/components", {"repository": "a b", "continuationToken": "t/1"})
        assert url == "https://x/service/rest/v1/components?repository=a+b&continuationToken=t%2F1"
