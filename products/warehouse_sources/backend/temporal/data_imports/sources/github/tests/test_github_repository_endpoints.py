import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from unittest import mock

import pyarrow as pa
import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.github import github
from products.warehouse_sources.backend.temporal.data_imports.sources.github.settings import GITHUB_ENDPOINTS

_CUTOFF = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)


def _response(body: Any, next_url: str | None = None, status_code: int = 200) -> mock.Mock:
    response = mock.Mock()
    response.status_code = status_code
    response.json.return_value = body
    response.headers = {"Link": f'<{next_url}>; rel="next"'} if next_url else {}
    return response


def _no_resume() -> mock.Mock:
    manager = mock.Mock()
    manager.can_resume.return_value = False
    return manager


def _run(
    endpoint: str, responses_by_url: dict[str, mock.Mock], **incremental: Any
) -> tuple[list[dict[str, Any]], list[str]]:
    calls: list[str] = []

    def fetch_page(url: str, *_args: Any, **_kwargs: Any) -> mock.Mock:
        calls.append(url)
        for needle in sorted(responses_by_url, key=len, reverse=True):
            if needle in url:
                return responses_by_url[needle]
        raise AssertionError(f"Unexpected URL requested: {url}")

    with mock.patch.object(github, "_fetch_page", side_effect=fetch_page):
        tables = list(
            github.get_rows(
                personal_access_token="tok",
                repository="acme/widgets",
                endpoint=endpoint,
                logger=mock.Mock(),
                resumable_source_manager=_no_resume(),
                **incremental,
            )
        )

    rows: list[dict[str, Any]] = []
    for table in tables:
        assert isinstance(table, pa.Table)
        rows.extend(table.to_pylist())
    return rows, calls


def _run_over_transport(endpoint: str) -> list[dict[str, Any]]:
    """Same walk as `_run`, but through the real `_fetch_page` so the response-status handling is
    exercised rather than stubbed out."""
    tables = list(
        github.get_rows(
            personal_access_token="tok",
            repository="acme/widgets",
            endpoint=endpoint,
            logger=mock.Mock(),
            resumable_source_manager=_no_resume(),
        )
    )

    rows: list[dict[str, Any]] = []
    for table in tables:
        assert isinstance(table, pa.Table)
        rows.extend(table.to_pylist())
    return rows


def _not_found_response() -> mock.Mock:
    response = mock.Mock(spec=requests.Response)
    response.status_code = 404
    response.ok = False
    response.headers = {}
    response.text = "Not Found"
    response.request = None
    response.raise_for_status.side_effect = requests.exceptions.HTTPError(
        "404 Client Error: Not Found for url", response=response
    )
    return response


class TestListParams:
    @parameterized.expand(
        [
            # A "plain" endpoint that receives the generic state/sort trio would be rejected by
            # GitHub: milestones only accepts sort=due_on|completeness, and the alert endpoints
            # define their own state enum with no "all" member.
            ("milestones", {"per_page", "state"}),
            ("branches", {"per_page"}),
            ("traffic_views", {"per_page"}),
            ("issue_events", {"per_page"}),
            ("forks", {"per_page", "sort"}),
            # /activity answers 422 on an unknown sort or state, so it must stay a plain read
            # carrying only the direction that makes the watermark stop correct.
            ("repository_activity", {"per_page", "direction"}),
            ("commit_comments", {"per_page"}),
            ("issue_types", {"per_page"}),
            # "sorted" endpoints keep sort/direction but must not send state.
            ("code_scanning_alerts", {"per_page", "sort", "direction"}),
            ("security_advisories", {"per_page", "sort", "direction"}),
            ("secret_scanning_alerts", {"per_page", "sort", "direction", "hide_secret"}),
            ("issue_comments", {"per_page", "sort", "direction"}),
            # The endpoints that shipped first keep the original shape.
            ("issues", {"per_page", "state", "sort", "direction"}),
            ("releases", {"per_page", "state", "sort", "direction"}),
        ]
    )
    def test_full_refresh_param_keys(self, endpoint: str, expected_keys: set[str]) -> None:
        params = github._build_initial_params(
            GITHUB_ENDPOINTS[endpoint],
            endpoint,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )

        assert set(params) == expected_keys

    @parameterized.expand(
        [
            # `since` bounds the incremental read server-side, so losing it turns every sync back
            # into a full history walk.
            ("issue_comments", "updated_at", True),
            ("pull_request_comments", "updated_at", True),
            # These endpoints have no `since` filter; sending one would be silently ignored and is
            # not what bounds them.
            ("code_scanning_alerts", "updated_at", False),
            ("security_advisories", "created_at", False),
        ]
    )
    def test_incremental_since(self, endpoint: str, incremental_field: str, expects_since: bool) -> None:
        params = github._build_initial_params(
            GITHUB_ENDPOINTS[endpoint],
            endpoint,
            should_use_incremental_field=True,
            db_incremental_field_last_value=_CUTOFF,
            incremental_field=incremental_field,
        )

        assert ("since" in params) is expects_since
        if expects_since:
            # The watermark, not the first-sync lookback floor, must bound a sync that has one.
            assert params["since"] == github._format_incremental_value(_CUTOFF)
        assert params["sort"] == incremental_field.removesuffix("_at")
        assert params["direction"] == GITHUB_ENDPOINTS[endpoint].sort_mode
        assert "state" not in params

    @parameterized.expand(
        [
            ("issue_comments",),
            ("pull_request_comments",),
        ]
    )
    def test_first_sync_since_floor(self, endpoint: str) -> None:
        # Without the floor the bootstrap walks every comment ever written before webhook mode can
        # activate, so dropping it turns connect-time into a full-history crawl on large repos.
        lookback = GITHUB_ENDPOINTS[endpoint].initial_lookback_days
        assert lookback

        params = github._build_initial_params(
            GITHUB_ENDPOINTS[endpoint],
            endpoint,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="updated_at",
        )

        floor = datetime.fromisoformat(params["since"].replace("Z", "+00:00"))
        expected = datetime.now(UTC) - timedelta(days=lookback)
        assert abs((expected - floor).total_seconds()) < 60

    def test_full_refresh_ignores_since_floor(self) -> None:
        # An explicit full refresh must still pull the whole history; the floor only bounds the
        # first incremental run.
        params = github._build_initial_params(
            GITHUB_ENDPOINTS["issue_comments"],
            "issue_comments",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )

        assert "since" not in params

    @parameterized.expand(
        [
            # issue_events and forks answer newest-first whatever we ask for, so reporting "asc" on
            # a first sync would make the pipeline checkpoint the watermark at ~now and strand the
            # rest of the history.
            ("issue_events", "desc"),
            ("forks", "desc"),
            ("repository_activity", "desc"),
            # Endpoints without the flag still start ascending and only flip once a cutoff exists.
            ("issue_comments", "asc"),
            ("milestones", "asc"),
        ]
    )
    def test_first_sync_sort_mode(self, endpoint: str, expected: str) -> None:
        assert (
            github._resolve_sort_mode(
                GITHUB_ENDPOINTS[endpoint],
                endpoint,
                should_use_incremental_field=True,
                db_incremental_field_last_value=None,
            )
            == expected
        )


class TestBodyTransforms:
    @parameterized.expand(
        [
            (
                "languages",
                {"Python": 1200, "TypeScript": 340},
                [
                    {"repository": "acme/widgets", "language": "Python", "bytes": 1200},
                    {"repository": "acme/widgets", "language": "TypeScript", "bytes": 340},
                ],
            ),
            (
                "topics",
                {"names": ["analytics", "hogql"]},
                [
                    {"repository": "acme/widgets", "name": "analytics"},
                    {"repository": "acme/widgets", "name": "hogql"},
                ],
            ),
            (
                "code_frequency_stats",
                [[1336280400, 120, -40], [1336885200, 3, 0]],
                [
                    {"week": 1336280400, "additions": 120, "deletions": -40},
                    {"week": 1336885200, "additions": 3, "deletions": 0},
                ],
            ),
            (
                "punch_card_stats",
                [[0, 13, 4], [2, 14, 25]],
                [
                    {"day": 0, "hour": 13, "commits": 4},
                    {"day": 2, "hour": 14, "commits": 25},
                ],
            ),
            (
                # The weekly counts arrive as arrays; the batcher lands them as their JSON encoding.
                "participation_stats",
                {"all": [1, 2], "owner": [1, 0]},
                [{"repository": "acme/widgets", "all": "[1,2]", "owner": "[1,0]"}],
            ),
            (
                "dependency_sbom",
                {"sbom": {"name": "acme/widgets", "packages": [{"SPDXID": "SPDXRef-pip-flask", "name": "flask"}]}},
                [
                    {
                        "repository": "acme/widgets",
                        "document_name": "acme/widgets",
                        "spdx_id": "SPDXRef-pip-flask",
                        "name": "flask",
                    }
                ],
            ),
            ("repository", {"id": 7, "full_name": "acme/widgets"}, [{"id": 7, "full_name": "acme/widgets"}]),
        ]
    )
    def test_non_row_shaped_bodies_become_rows(self, endpoint: str, body: Any, expected: list[dict[str, Any]]) -> None:
        # These endpoints answer with a map, a positional array, or a bare object. Without the
        # transform the pipeline would either write nothing or try to batch non-dict values.
        rows, _calls = _run(endpoint, {"api.github.com": _response(body)})

        assert rows == expected

    def test_statistics_not_ready_syncs_zero_rows(self) -> None:
        # GitHub answers 202 with no usable body while it recomputes a /stats aggregate. That must
        # sync nothing and end cleanly, not raise and retry the activity forever.
        rows, _calls = _run("contributor_stats", {"api.github.com": _response(None, status_code=202)})

        assert rows == []

    def test_statistics_no_content_syncs_zero_rows(self) -> None:
        # GitHub answers 204 No Content on the /stats/* endpoints for a repo with no commit activity.
        # The empty body must sync zero rows, not crash on response.json() (a JSONDecodeError).
        no_content = _response(None, status_code=204)
        no_content.json.side_effect = requests.exceptions.JSONDecodeError("Expecting value", "", 0)

        rows, _calls = _run("contributor_stats", {"api.github.com": no_content})

        assert rows == []

    def test_envelope_endpoint_unwraps_named_key(self) -> None:
        rows, _calls = _run(
            "environments",
            {"api.github.com": _response({"total_count": 1, "environments": [{"id": 3, "name": "production"}]})},
        )

        assert rows == [{"id": 3, "name": "production"}]


class TestNotFoundTolerance:
    @parameterized.expand(
        [
            # Issue types and repository teams are inherited from an organization owner, so a
            # user-owned repository 404s on both even with a perfectly good token. Failing there
            # would break the whole schema for every personal repository.
            ("issue_types", True),
            ("repository_teams", True),
            # A plain repo-scoped table keeps 404 fatal once the repository probe 404s too, so a
            # genuinely wrong or revoked repository still fails loud instead of quietly syncing an
            # empty table forever.
            ("labels", False),
        ]
    )
    def test_404_syncs_zero_rows_only_where_the_resource_is_optional(self, endpoint: str, tolerated: bool) -> None:
        session = mock.Mock()
        session.request.return_value = _not_found_response()

        with mock.patch.object(github, "make_tracked_session", return_value=session):
            if not tolerated:
                with pytest.raises(github.GithubRepositoryNotFoundError):
                    _run_over_transport(endpoint)
                return
            assert _run_over_transport(endpoint) == []


class TestRowMappers:
    def test_secret_scanning_alert_never_carries_the_secret(self) -> None:
        # The leaked credential itself must never land in a customer's warehouse, whichever API
        # version the source is pinned to (hide_secret is a newer parameter).
        rows, _calls = _run(
            "secret_scanning_alerts",
            {
                "api.github.com": _response(
                    [{"number": 4, "secret": "ghp_realtokenvalue", "secret_type": "github_personal_access_token"}]
                )
            },
        )

        assert rows == [{"number": 4, "secret_type": "github_personal_access_token"}]

    def test_contributor_stats_flattens_author_and_drops_anonymous(self) -> None:
        # author_id is this table's primary key, so an unattributed row would seed a null key and
        # make every later merge multi-match.
        rows, _calls = _run(
            "contributor_stats",
            {
                "api.github.com": _response(
                    [
                        {"author": {"id": 11, "login": "ada"}, "total": 9, "weeks": []},
                        {"author": None, "total": 2, "weeks": []},
                    ]
                )
            },
        )

        assert [(row["author_id"], row["author_login"]) for row in rows] == [(11, "ada")]

    @parameterized.expand(
        [
            # /repos/{repo} answers with a single repository object; a fork's parent/source are
            # nested repository objects that can each carry their own clone token.
            (
                "repository",
                {
                    "id": 7,
                    "temp_clone_token": "v1_realclonetoken",
                    "parent": {"id": 3, "temp_clone_token": "v1_parenttoken"},
                    "source": {"id": 3, "temp_clone_token": "v1_sourcetoken"},
                    "template_repository": {"id": 1, "temp_clone_token": "v1_templatetoken"},
                },
            ),
            # /forks answers with a list of repository objects, batched via the item mapper.
            (
                "forks",
                [
                    {
                        "id": 9,
                        "temp_clone_token": "v1_forktoken",
                        "parent": {"id": 7, "temp_clone_token": "v1_parenttoken"},
                    }
                ],
            ),
        ]
    )
    def test_repository_clone_token_never_reaches_the_warehouse(self, endpoint: str, body: Any) -> None:
        # temp_clone_token is a live credential to clone the private repo. The repository and forks
        # tables are default-on, so a warehouse user without GitHub access could otherwise read it.
        # Nested repository objects land as JSON strings, so assert over the serialized row to catch
        # the token wherever it ends up.
        rows, _calls = _run(endpoint, {"api.github.com": _response(body)})

        assert rows, "expected at least one row"
        for row in rows:
            serialized = json.dumps(row, default=str)
            assert "temp_clone_token" not in serialized


class TestCommitFanOut:
    def test_commit_statuses_inject_sha_and_stop_at_the_watermark(self) -> None:
        # The commit cursor only exists after the parent mapper flattens commit.author.date onto the
        # row. Without it the walk never recognizes an old commit, so every incremental sync
        # re-fans-out the repository's entire history — one request per commit.
        responses = {
            "/commits/new-sha/statuses": _response(
                [{"id": 900, "state": "success", "created_at": "2026-01-20T10:00:00Z"}]
            ),
            "/commits/old-sha/statuses": _response(
                [{"id": 800, "state": "failure", "created_at": "2025-12-01T10:00:00Z"}]
            ),
            "/commits": _response(
                [
                    {"sha": "new-sha", "commit": {"author": {"date": "2026-01-20T09:00:00Z"}}},
                    {"sha": "old-sha", "commit": {"author": {"date": "2025-12-01T09:00:00Z"}}},
                ]
            ),
        }

        rows, calls = _run(
            "commit_statuses",
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=_CUTOFF,
        )

        assert rows == [{"id": 900, "state": "success", "created_at": "2026-01-20T10:00:00Z", "commit_sha": "new-sha"}]
        assert not any("old-sha" in call for call in calls)

    def test_check_runs_fan_out_unwraps_envelope(self) -> None:
        responses = {
            "/commits/new-sha/check-runs": _response(
                {"total_count": 1, "check_runs": [{"id": 21, "name": "lint", "started_at": "2026-01-20T10:00:00Z"}]}
            ),
            "/commits": _response([{"sha": "new-sha", "commit": {"author": {"date": "2026-01-20T09:00:00Z"}}}]),
        }

        rows, calls = _run(
            "check_runs",
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=_CUTOFF,
        )

        assert rows == [{"id": 21, "name": "lint", "started_at": "2026-01-20T10:00:00Z"}]
        # filter=all is what surfaces re-runs rather than only the latest run per check name.
        assert any("filter=all" in call for call in calls)
