import json
from datetime import UTC, datetime
from typing import Any, Optional

import pytest
from unittest import mock

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.coveralls.coveralls import (
    COVERALLS_BASE_URL,
    MAX_REPOSITORIES,
    CoverallsResumeConfig,
    CoverallsRetryableError,
    _builds_url,
    _fetch_json,
    _incremental_cutoff,
    coveralls_source,
    get_builds_rows,
    get_repository_rows,
    parse_repositories,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coveralls.settings import COVERALLS_ENDPOINTS

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.coveralls.coveralls"


def _response(status: int = 200, body: Optional[dict[str, Any]] = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status
    resp.ok = 200 <= status < 300
    resp.json.return_value = body or {}
    resp.text = json.dumps(body or {})
    if not resp.ok:
        resp.raise_for_status.side_effect = requests.HTTPError(
            f"{status} Client Error for url: {COVERALLS_BASE_URL}", response=requests.Response()
        )
    return resp


def _build(build_id: int, created_at: str, repo_name: str | None = "acme/widgets") -> dict[str, Any]:
    build: dict[str, Any] = {
        "id": build_id,
        "branch": "master",
        "commit_sha": f"sha-{build_id}",
        "created_at": created_at,
        "covered_percent": 90.0,
    }
    if repo_name is not None:
        build["repo_name"] = repo_name
    return build


def _builds_page(page: int, pages: int, builds: list[dict[str, Any]]) -> dict[str, Any]:
    return {"page": page, "pages": pages, "total": pages * 10, "builds": builds}


def _manager(state: CoverallsResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = state is not None
    manager.load_state.return_value = state
    return manager


class TestParseRepositories:
    @pytest.mark.parametrize("raw", [None, "", "   \n  ", " , , ", "not-owner-repo"])
    def test_invalid_raises(self, raw):
        with pytest.raises(ValueError):
            parse_repositories(raw)

    def test_rejects_too_many_repositories(self):
        raw = "\n".join(f"acme/repo{i}" for i in range(MAX_REPOSITORIES + 1))
        with pytest.raises(ValueError, match="Too many repositories"):
            parse_repositories(raw)


# tenacity exposes the undecorated function via `__wrapped__` so status classification can be
# asserted without waiting through retry backoff.
_fetch_once = _fetch_json.__wrapped__  # type: ignore[attr-defined]


class TestFetchJson:
    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_statuses_raise_retryable(self, status):
        session = mock.MagicMock()
        session.get.return_value = _response(status)

        with pytest.raises(CoverallsRetryableError):
            _fetch_once(session, "https://coveralls.io/x", {}, structlog.get_logger())

    def test_other_client_error_raises(self):
        session = mock.MagicMock()
        session.get.return_value = _response(401)

        with pytest.raises(requests.HTTPError):
            _fetch_once(session, "https://coveralls.io/x", {}, structlog.get_logger())


class TestIncrementalCutoff:
    @pytest.mark.parametrize(
        "value, lookback, expected",
        [
            # The DB hands the watermark back as a datetime or an ISO string; both must resolve.
            (datetime(2021, 4, 16, 12, 0, tzinfo=UTC), None, datetime(2021, 4, 16, 12, 0, tzinfo=UTC)),
            ("2021-04-16T12:00:00Z", None, datetime(2021, 4, 16, 12, 0, tzinfo=UTC)),
            # The safety lookback re-pulls a window before the watermark; merge dedupes it.
            (
                datetime(2021, 4, 16, 12, 0, tzinfo=UTC),
                COVERALLS_ENDPOINTS["builds"].incremental_lookback,
                datetime(2021, 4, 15, 12, 0, tzinfo=UTC),
            ),
            (None, None, None),
            ("not-a-date", None, None),
        ],
    )
    def test_cutoff(self, value, lookback, expected):
        assert _incremental_cutoff(value, lookback) == expected


class TestGetBuildsRows:
    def test_stops_on_empty_page(self):
        # Past-the-end pages return an empty builds list; the walk must terminate rather than loop.
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(200, _builds_page(1, 0, []))

            batches = list(get_builds_rows("github", ["acme/widgets"], structlog.get_logger(), _manager(), None))

        assert batches == []
        assert mock_session.return_value.get.call_count == 1

    def test_incremental_stops_at_watermark(self):
        # The feed is newest-first: once a build at or before the cutoff shows up, later pages are
        # all older, so an incremental sync must not fetch them.
        cutoff = datetime(2021, 4, 15, 0, 0, tzinfo=UTC)
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(
                200,
                _builds_page(1, 5, [_build(20, "2021-04-16T17:46:20Z"), _build(10, "2021-04-13T18:45:20Z")]),
            )

            batches = list(get_builds_rows("github", ["acme/widgets"], structlog.get_logger(), _manager(), cutoff))

        # The page containing the old build is still yielded (merge dedupes), but no further page is fetched.
        assert len(batches) == 1
        assert mock_session.return_value.get.call_count == 1

    def test_skips_404_repository_and_continues(self):
        # One typo'd or private repository must not kill the sync for the others.
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = [
                _response(404),
                _response(200, _builds_page(1, 1, [_build(30, "2021-04-16T17:46:20Z", repo_name="acme/gadgets")])),
            ]

            batches = list(
                get_builds_rows("github", ["acme/nope", "acme/gadgets"], structlog.get_logger(), _manager(), None)
            )

        assert [[row["id"] for row in batch] for batch in batches] == [[30]]

    def test_saves_state_after_each_page_and_between_repositories(self):
        manager = _manager()
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = [
                _response(200, _builds_page(1, 2, [_build(20, "2021-04-16T17:46:20Z")])),
                _response(200, _builds_page(2, 2, [_build(10, "2021-04-13T18:45:20Z")])),
                _response(200, _builds_page(1, 1, [_build(30, "2021-04-17T00:00:00Z", repo_name="acme/gadgets")])),
            ]

            generator = get_builds_rows(
                "github", ["acme/widgets", "acme/gadgets"], structlog.get_logger(), manager, None
            )

            next(generator)
            # State is only saved AFTER a page is yielded and consumed, so a crash re-yields it.
            manager.save_state.assert_not_called()

            next(generator)
            manager.save_state.assert_called_once_with(CoverallsResumeConfig(repository="acme/widgets", page=2))

            list(generator)

        assert manager.save_state.call_args_list[-1] == mock.call(
            CoverallsResumeConfig(repository="acme/gadgets", page=1)
        )

    def test_resumes_from_saved_repository_and_page(self):
        # A resumed sync must skip completed repositories and start the bookmarked one at the saved
        # page, not restart the whole walk.
        manager = _manager(CoverallsResumeConfig(repository="acme/gadgets", page=3))
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(
                200, _builds_page(3, 3, [_build(5, "2021-01-01T00:00:00Z", repo_name="acme/gadgets")])
            )

            batches = list(
                get_builds_rows("github", ["acme/widgets", "acme/gadgets"], structlog.get_logger(), manager, None)
            )

        assert len(batches) == 1
        called_url = mock_session.return_value.get.call_args[0][0]
        assert called_url == _builds_url("github", "acme/gadgets", 3)


class TestGetRepositoryRows:
    def test_requires_api_token(self):
        with pytest.raises(ValueError, match="personal API token"):
            list(get_repository_rows("github", ["acme/widgets"], None, structlog.get_logger()))

    def test_yields_row_per_repository_with_key_columns(self):
        # `service` and `name` form the primary key, so they must be present even if the API
        # response omits them.
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = [
                _response(200, {"comment_on_pull_requests": True, "repo_token": "secret-upload-token"}),
                _response(404),
                _response(200, {"name": "acme/gadgets", "send_build_status": False, "token": "secret"}),
            ]

            batches = list(
                get_repository_rows(
                    "github", ["acme/widgets", "acme/nope", "acme/gadgets"], "tok", structlog.get_logger()
                )
            )

        assert len(batches) == 2
        assert batches[0][0]["service"] == "github"
        assert batches[0][0]["name"] == "acme/widgets"
        assert batches[1][0]["name"] == "acme/gadgets"
        # The response's secret coverage-upload token must never be persisted as warehouse data.
        for batch in batches:
            assert not any("token" in key for key in batch[0])


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected_valid",
        [
            (200, True),
            (404, False),
            (500, False),
        ],
    )
    def test_builds_feed_status_mapping(self, status, expected_valid):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(status)

            is_valid, _ = validate_credentials("github", "acme/widgets", None)

        assert is_valid is expected_valid

    def test_invalid_repositories_fail_without_request(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            is_valid, message = validate_credentials("github", "", None)

        assert is_valid is False
        assert message is not None
        mock_session.return_value.get.assert_not_called()

    def test_network_error_is_invalid(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")

            is_valid, message = validate_credentials("github", "acme/widgets", None)

        assert is_valid is False
        assert message is not None

    def test_repositories_schema_requires_token(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(200)

            is_valid, message = validate_credentials("github", "acme/widgets", None, schema_name="repositories")

        assert is_valid is False
        assert message is not None and "token" in message

    @pytest.mark.parametrize(
        "token_status, expected_valid",
        [
            (200, True),
            (401, False),
            # Coveralls answers 404 (not 401) for unauthorized repos-API requests too.
            (404, False),
        ],
    )
    def test_repositories_schema_probes_token(self, token_status, expected_valid):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = [_response(200), _response(token_status)]

            is_valid, _ = validate_credentials("github", "acme/widgets", "tok", schema_name="repositories")

        assert is_valid is expected_valid


class TestCoverallsSource:
    def test_only_builds_is_partitioned(self):
        builds = coveralls_source(
            endpoint="builds",
            service="github",
            repositories_raw="acme/widgets",
            api_token=None,
            logger=structlog.get_logger(),
            resumable_source_manager=_manager(),
        )
        repositories = coveralls_source(
            endpoint="repositories",
            service="github",
            repositories_raw="acme/widgets",
            api_token="tok",
            logger=structlog.get_logger(),
            resumable_source_manager=_manager(),
        )

        assert builds.partition_mode == "datetime"
        assert builds.partition_keys == ["created_at"]
        assert repositories.partition_mode is None
        assert repositories.partition_keys is None

    def test_invalid_repositories_raise(self):
        with pytest.raises(ValueError):
            coveralls_source(
                endpoint="builds",
                service="github",
                repositories_raw="",
                api_token=None,
                logger=structlog.get_logger(),
                resumable_source_manager=_manager(),
            )
