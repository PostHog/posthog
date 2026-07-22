from datetime import UTC, datetime
from typing import Any

from unittest import mock

import pyarrow as pa
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.github import github


def _response(rows: list[dict[str, Any]], next_url: str | None = None) -> mock.Mock:
    response = mock.Mock()
    response.json.return_value = rows
    response.headers = {"Link": f'<{next_url}>; rel="next"'} if next_url else {}
    return response


def _no_resume() -> mock.Mock:
    manager = mock.Mock()
    manager.can_resume.return_value = False
    return manager


def _event(event_id: int, event: str, created_at: str, issue_number: int, **extra: Any) -> dict[str, Any]:
    return {
        "id": event_id,
        "node_id": f"node-{event_id}",
        "event": event,
        "created_at": created_at,
        "actor": {"login": "ada", "id": 1},
        "issue": {"number": issue_number, "title": "big nested issue snapshot", "pull_request": {}},
        **extra,
    }


def _run(endpoint: str, responses: list[mock.Mock], **incremental: Any) -> tuple[list[dict[str, Any]], list[str]]:
    calls: list[str] = []

    def fetch_page(url: str, *_args: Any, **_kwargs: Any) -> mock.Mock:
        calls.append(url)
        return responses[len(calls) - 1]

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


def test_lands_every_event_type_as_a_fixed_envelope() -> None:
    # Every event type must land — the incremental watermark is computed from landed rows, so
    # filtering at the source would pin the cursor at the last interesting event and re-crawl
    # the whole unfiltered stream back to it on every sync. Rows must share one fixed column
    # set regardless of event type (per-type payloads and the nested issue snapshot dropped,
    # ghost-user actor landing as NULL, not an absent key), or the batch schema drifts.
    rows, calls = _run(
        "issue_events",
        [
            _response(
                [
                    _event(1, "ready_for_review", "2026-01-20T10:00:00Z", 42),
                    _event(2, "labeled", "2026-01-20T09:00:00Z", 42, label={"name": "bug"}),
                    {
                        "id": 3,
                        "event": "closed",
                        "created_at": "2026-01-20T08:00:00Z",
                        "actor": None,
                        "issue": {"number": 7},
                    },
                ]
            )
        ],
    )

    envelope = {"id", "node_id", "event", "created_at", "issue_number", "actor_login"}
    assert [set(row) for row in rows] == [envelope] * 3
    assert [(row["id"], row["event"], row["issue_number"]) for row in rows] == [
        (1, "ready_for_review", 42),
        (2, "labeled", 42),
        (3, "closed", 7),
    ]
    assert rows[0]["actor_login"] == "ada"
    assert rows[2]["actor_login"] is None  # ghost user
    # No state/sort/direction params: the endpoint honors none, and the desc walk relies on
    # the API's fixed newest-first order.
    assert "sort=" not in calls[0] and "state=" not in calls[0]


@parameterized.expand(
    [
        # First incremental sync (no watermark) and explicit full refresh both walk un-cursored;
        # without the lookback floor either would paginate the repository's entire issue-event
        # history (every label/assign/close since repo creation) — the egress blowup this
        # endpoint's design avoids. The walk must stop at the page crossing the one-day floor.
        ("first_incremental_sync", {"should_use_incremental_field": True, "db_incremental_field_last_value": None}),
        ("full_refresh", {}),
    ]
)
def test_un_cursored_walk_floors_at_lookback(_name: str, incremental: dict[str, Any]) -> None:
    now = datetime(2026, 1, 21, 12, 0, tzinfo=UTC)
    page_one = _response(
        [_event(1, "ready_for_review", "2026-01-21T10:00:00Z", 42)],
        next_url="https://api.github.com/repos/acme/widgets/issues/events?page=2",
    )
    # Crosses below now - 1 day; anything after this page is history.
    page_two = _response(
        [_event(2, "convert_to_draft", "2026-01-19T10:00:00Z", 41)],
        next_url="https://api.github.com/repos/acme/widgets/issues/events?page=3",
    )

    with mock.patch.object(github, "_now_utc", return_value=now):
        rows, calls = _run("issue_events", [page_one, page_two], **incremental)

    assert len(calls) == 2
    assert [row["id"] for row in rows] == [1, 2]


def test_lookback_zero_marker_is_excluded_from_the_floor() -> None:
    # initial_lookback_days=0 is the webhook-only marker (workflow_runs), not a zero-day floor:
    # a legacy poll-mode schema's first incremental sync must keep crawling history, not freeze
    # at now importing a single page — the regression the webhook-only rollout's review closed.
    page_one = mock.Mock()
    page_one.json.return_value = {"workflow_runs": [{"id": 10, "created_at": "2026-01-20T10:00:00Z"}]}
    page_one.headers = {"Link": '<https://api.github.com/repos/acme/widgets/actions/runs?page=2>; rel="next"'}
    page_two = mock.Mock()
    page_two.json.return_value = {"workflow_runs": [{"id": 9, "created_at": "2026-01-01T10:00:00Z"}]}
    page_two.headers = {}

    rows, calls = _run(
        "workflow_runs",
        [page_one, page_two],
        should_use_incremental_field=True,
        db_incremental_field_last_value=None,
    )

    # Both pages fetched: no floor fired, the walk followed pagination to the end of history.
    assert len(calls) == 2
    assert [row["id"] for row in rows] == [10, 9]


@parameterized.expand(
    [
        # First sync included: the API always returns newest-first, so reporting asc would let the
        # pipeline persist the created_at watermark per batch and strand rows on an interrupted sync.
        (None,),
        (datetime(2026, 1, 25, tzinfo=UTC),),
    ]
)
def test_resolve_sort_mode_is_desc_on_every_sync(last_value: datetime | None) -> None:
    config = github.GITHUB_ENDPOINTS["issue_events"]
    assert github._resolve_sort_mode(config, "issue_events", True, last_value) == "desc"
