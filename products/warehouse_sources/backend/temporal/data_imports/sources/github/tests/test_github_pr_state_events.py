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


def _event(event_id: int, event: str, created_at: str, pr_number: int) -> dict[str, Any]:
    return {
        "id": event_id,
        "event": event,
        "created_at": created_at,
        "actor": {"login": "ada", "id": 1},
        "issue": {"number": pr_number, "title": "big nested issue snapshot", "pull_request": {}},
    }


def _run(responses: list[mock.Mock], **incremental: Any) -> tuple[list[dict[str, Any]], list[str]]:
    calls: list[str] = []

    def fetch_page(url: str, *_args: Any, **_kwargs: Any) -> mock.Mock:
        calls.append(url)
        return responses[len(calls) - 1]

    with mock.patch.object(github, "_fetch_page", side_effect=fetch_page):
        tables = list(
            github.get_rows(
                personal_access_token="tok",
                repository="acme/widgets",
                endpoint="pr_state_events",
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


def test_filters_to_draft_transitions_and_flattens_pr_number() -> None:
    # The repo-wide issue events list mixes every event type; only the draft/ready transitions may
    # land, each carrying its PR number with the bulky nested issue snapshot dropped (an immutable
    # event row must not embed a mutable PR copy). A regression here either bloats the table with
    # label/assign noise or breaks PR attribution for the ready-to-merge metric.
    rows, calls = _run(
        [
            _response(
                [
                    _event(1, "ready_for_review", "2026-01-20T10:00:00Z", 42),
                    {"id": 2, "event": "labeled", "created_at": "2026-01-20T09:00:00Z", "issue": {"number": 42}},
                    _event(3, "convert_to_draft", "2026-01-20T08:00:00Z", 42),
                    {"id": 4, "event": "closed", "created_at": "2026-01-20T07:00:00Z", "issue": {"number": 7}},
                ]
            )
        ]
    )

    assert [(row["id"], row["event"], row["pr_number"]) for row in rows] == [
        (1, "ready_for_review", 42),
        (3, "convert_to_draft", 42),
    ]
    assert all("issue" not in row for row in rows)
    assert rows[0]["actor_login"] == "ada"
    # No state/sort/direction params: the endpoint rejects none but honors none either, and the
    # desc walk relies on the API's fixed newest-first order.
    assert "sort=" not in calls[0] and "state=" not in calls[0]


def test_first_sync_floors_at_lookback_instead_of_crawling_history() -> None:
    # First incremental sync has no watermark; without the lookback floor the desc walk would
    # paginate the repository's entire issue-event history (every label/assign/close since repo
    # creation) — the exact egress blowup this endpoint's design avoids. The walk must stop at
    # the page that crosses the one-day floor and never request the next one.
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
        rows, calls = _run(
            [page_one, page_two],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )

    assert len(calls) == 2
    assert [row["id"] for row in rows] == [1, 2]


@parameterized.expand(
    [
        # First sync included: the API always returns newest-first, so reporting asc would let the
        # pipeline persist the created_at watermark per batch and strand rows on an interrupted sync.
        (None,),
        (datetime(2026, 1, 25, tzinfo=UTC),),
    ]
)
def test_resolve_sort_mode_is_desc_on_every_sync(last_value: datetime | None) -> None:
    config = github.GITHUB_ENDPOINTS["pr_state_events"]
    assert github._resolve_sort_mode(config, "pr_state_events", True, last_value) == "desc"
