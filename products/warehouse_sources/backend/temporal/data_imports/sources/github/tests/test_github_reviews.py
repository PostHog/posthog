from datetime import UTC, datetime
from typing import Any

from unittest import mock

import pyarrow as pa

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


def _run_reviews_fan_out(
    responses_by_url: dict[str, mock.Mock], **incremental: Any
) -> tuple[list[dict[str, Any]], list[str]]:
    calls: list[str] = []

    def fetch_page(url: str, *_args: Any, **_kwargs: Any) -> mock.Mock:
        calls.append(url)
        # Longest-prefix match so a PR's /reviews path never routes to the /pulls list.
        for needle in sorted(responses_by_url, key=len, reverse=True):
            if needle in url:
                return responses_by_url[needle]
        raise AssertionError(f"Unexpected URL requested: {url}")

    with mock.patch.object(github, "_fetch_page", side_effect=fetch_page):
        tables = list(
            github.get_rows(
                personal_access_token="tok",
                repository="acme/widgets",
                endpoint="reviews",
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


def test_reviews_fan_out_drops_pending_and_injects_pr_number() -> None:
    # PENDING reviews come back with submitted_at=null and must be dropped before rows leave the
    # fan-out walk, otherwise a null lands in the partition/cursor column. This also guards that the
    # item filter is applied on the fan-out path at all (it historically ran only on the top-level
    # path), and that each surviving review carries its PR number injected from the parent.
    responses = {
        "/pulls/10/reviews": _response(
            [
                {"id": 500, "state": "APPROVED", "submitted_at": "2026-01-20T10:00:00Z", "user": {"login": "ada"}},
                {"id": 501, "state": "PENDING", "submitted_at": None, "user": {"login": "self"}},
                {
                    "id": 502,
                    "state": "CHANGES_REQUESTED",
                    "submitted_at": "2026-01-21T10:00:00Z",
                    "user": {"login": "grace"},
                },
            ]
        ),
        "/pulls": _response([{"id": 10, "number": 10, "updated_at": "2026-01-30T10:00:00Z"}]),
    }

    rows, _calls = _run_reviews_fan_out(responses)

    assert [row["id"] for row in rows] == [500, 502]
    assert all(row["pr_number"] == 10 for row in rows)
    # Review fields pass through untouched (scalar columns; nested structs like user are
    # JSON-serialized by the pipeline on write, so don't pin their shape here).
    assert [row["state"] for row in rows] == ["APPROVED", "CHANGES_REQUESTED"]
    assert rows[0]["submitted_at"] == "2026-01-20T10:00:00Z"


def test_reviews_parent_walk_bounds_on_pr_updated_at_not_submitted_at() -> None:
    # The child incremental field is submitted_at, which pull requests do not carry. The parent walk
    # must bound on the PR's updated_at instead. With a watermark set, a PR whose updated_at predates
    # it is skipped (no /reviews request), and a PR above it is fanned out. If the parent-cursor
    # decoupling regressed, the walk would read parent["submitted_at"] = None, skip nothing, and fan
    # out every PR. This pins that it reads updated_at.
    watermark = datetime(2026, 1, 25, tzinfo=UTC)
    responses = {
        "/pulls/11/reviews": _response(
            [{"id": 600, "state": "APPROVED", "submitted_at": "2026-01-28T10:00:00Z", "user": {"login": "ada"}}]
        ),
        "/pulls/12/reviews": _response(
            [{"id": 601, "state": "APPROVED", "submitted_at": "2026-01-10T10:00:00Z", "user": {"login": "bob"}}]
        ),
        # PR 11 updated after the watermark; PR 12 updated before it. Newest-first (desc) order.
        "/pulls": _response(
            [
                {"id": 11, "number": 11, "updated_at": "2026-01-28T10:00:00Z"},
                {"id": 12, "number": 12, "updated_at": "2026-01-20T10:00:00Z"},
            ]
        ),
    }

    rows, calls = _run_reviews_fan_out(
        responses,
        should_use_incremental_field=True,
        db_incremental_field_last_value=watermark,
        incremental_field="submitted_at",
    )

    assert [row["id"] for row in rows] == [600]
    assert any("/pulls/11/reviews" in c for c in calls)
    assert not any("/pulls/12/reviews" in c for c in calls)


def test_reviews_parent_walk_requests_pull_requests_sorted_updated_desc() -> None:
    # The parent list URL must request pull_requests sorted by updated descending once a cutoff
    # exists, so the desc early-stop bounding is correct. Without the sort the PRs would arrive in
    # GitHub's default created-asc order and _should_stop_desc would halt on the first old row,
    # dropping newer PRs.
    watermark = datetime(2026, 1, 25, tzinfo=UTC)
    responses = {
        "/pulls/11/reviews": _response(
            [{"id": 600, "state": "APPROVED", "submitted_at": "2026-01-28T10:00:00Z", "user": {"login": "ada"}}]
        ),
        "/pulls": _response([{"id": 11, "number": 11, "updated_at": "2026-01-28T10:00:00Z"}]),
    }

    _rows, calls = _run_reviews_fan_out(
        responses,
        should_use_incremental_field=True,
        db_incremental_field_last_value=watermark,
        incremental_field="submitted_at",
    )

    parent_call = next(c for c in calls if "/pulls?" in c)
    assert "sort=updated" in parent_call
    assert "direction=desc" in parent_call
