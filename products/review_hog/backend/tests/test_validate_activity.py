import contextlib
import dataclasses
from collections.abc import Iterator

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.testing import ActivityEnvironment

from products.review_hog.backend.reviewer.artefact_content import PRSnapshotArtefact
from products.review_hog.backend.reviewer.constants import VALIDATION_MAX_ATTEMPTS
from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, LineRange
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk, ChunksList, FileInfo
from products.review_hog.backend.temporal.activities import ValidateChunkInput, validate_chunk_activity

_MODULE = "products.review_hog.backend.temporal.activities"
_CHUNK_ID = 3


def _issue(issue_number: int) -> Issue:
    return Issue(
        id=f"1-{_CHUNK_ID}-{issue_number}",
        title=f"finding {issue_number}",
        file="a.py",
        lines=[LineRange(start=1)],
        issue="the problem",
        suggestion="the fix",
        priority=IssuePriority.SHOULD_FIX,
    )


def _verdict() -> IssueValidation:
    return IssueValidation(is_valid=True, argumentation="checks out")


def _input(issues: list[Issue]) -> ValidateChunkInput:
    return ValidateChunkInput(
        team_id=1,
        user_id=2,
        report_id="rep-1",
        head_sha="sha1",
        repository="o/r",
        branch="feat",
        run_index=1,
        chunk_id=_CHUNK_ID,
        issue_ids=[issue.id for issue in issues],
        skill_name="s-val",
        skill_version=1,
    )


def _snapshot() -> PRSnapshotArtefact:
    return PRSnapshotArtefact(
        head_sha="sha1",
        pr_metadata=PRMetadata(
            number=1,
            title="t",
            state="open",
            draft=False,
            created_at="c",
            updated_at="u",
            author="octocat",
            base_branch="main",
            head_branch="feat",
            commits=1,
            additions=1,
            deletions=0,
            changed_files=1,
        ),
        pr_comments=[],
        pr_files=[],
    )


def _env(attempt: int) -> ActivityEnvironment:
    env = ActivityEnvironment()
    env.info = dataclasses.replace(env.info, attempt=attempt)
    return env


@contextlib.contextmanager
def _chunk_context(issues: list[Issue], done: dict[str, IssueValidation]) -> Iterator[None]:
    # The activity receives only issue ids and reloads content from the finding rows — the loader
    # is patched to hand back the live issues the test built.
    with (
        patch(f"{_MODULE}.Heartbeater"),
        patch(f"{_MODULE}.load_run_issues", return_value=issues),
        patch(f"{_MODULE}.load_run_validations", return_value=done),
        patch(f"{_MODULE}.load_pr_snapshot", return_value=_snapshot()),
        patch(
            f"{_MODULE}.load_chunk_set",
            return_value=ChunksList(chunks=[Chunk(chunk_id=_CHUNK_ID, files=[FileInfo(filename="a.py")])]),
        ),
    ):
        yield


@pytest.mark.asyncio
async def test_turn_failure_fails_the_activity_so_temporal_retries() -> None:
    # The silent-loss bug: a failed turn used to be skipped with the activity returning success, so
    # Temporal never retried and the issue lost its verdict. It must fail the activity instead —
    # keeping the verdicts persisted before the failure, and never re-sending already-done issues.
    done_issue, ok_issue, failing_issue = _issue(1), _issue(2), _issue(3)
    session = object()
    mock_start = AsyncMock(return_value=(session, _verdict()))
    mock_continue = AsyncMock(side_effect=RuntimeError("upstream timeout"))
    mock_end = AsyncMock()
    mock_persist = MagicMock(return_value=True)
    env = _env(attempt=1)
    with (
        _chunk_context(issues=[done_issue, ok_issue, failing_issue], done={done_issue.id: _verdict()}),
        patch(f"{_MODULE}.persist_verdict", mock_persist),
        patch(f"{_MODULE}.start_sandbox_session", mock_start),
        patch(f"{_MODULE}.continue_sandbox_session", mock_continue),
        patch(f"{_MODULE}.end_sandbox_session", mock_end),
    ):
        with pytest.raises(RuntimeError):
            await env.run(validate_chunk_activity, _input([done_issue, ok_issue, failing_issue]))

    assert mock_start.call_count == 1  # only the first pending issue opened the session — not the done one
    assert mock_persist.call_count == 1
    assert mock_persist.call_args.kwargs["issue"].id == ok_issue.id
    mock_end.assert_awaited_once_with(session)
    # The session's Temporal workflow id is branded with the review's workflow id + step, lowercased.
    expected_prefix = f"{env.info.workflow_id}:validation-c{_CHUNK_ID}".lower()
    assert mock_start.call_args.kwargs["workflow_id_prefix"] == expected_prefix


@pytest.mark.asyncio
async def test_final_attempt_skips_the_failed_turn_and_continues_on_a_fresh_session() -> None:
    # Out of retries, one failed turn must not sink the chunk (via the failure floor, that would kill
    # a single-chunk run): the issue is skipped and the remaining ones get a fresh session — the old
    # one may be wedged after the failed turn.
    ok_issue, failing_issue, last_issue = _issue(1), _issue(2), _issue(3)
    first_session, fresh_session = object(), object()
    mock_start = AsyncMock(side_effect=[(first_session, _verdict()), (fresh_session, _verdict())])
    mock_continue = AsyncMock(side_effect=RuntimeError("upstream timeout"))
    mock_end = AsyncMock()
    mock_persist = MagicMock(return_value=True)
    with (
        _chunk_context(issues=[ok_issue, failing_issue, last_issue], done={}),
        patch(f"{_MODULE}.persist_verdict", mock_persist),
        patch(f"{_MODULE}.start_sandbox_session", mock_start),
        patch(f"{_MODULE}.continue_sandbox_session", mock_continue),
        patch(f"{_MODULE}.end_sandbox_session", mock_end),
    ):
        result = await _env(attempt=VALIDATION_MAX_ATTEMPTS).run(
            validate_chunk_activity, _input([ok_issue, failing_issue, last_issue])
        )

    assert result.validated_count == 2
    assert [call.kwargs["issue"].id for call in mock_persist.call_args_list] == [ok_issue.id, last_issue.id]
    assert mock_continue.call_count == 1  # the last issue went through a fresh start, not the wedged session
    assert [call.args[0] for call in mock_end.await_args_list] == [first_session, fresh_session]


@pytest.mark.asyncio
async def test_session_open_failure_raises_even_on_the_final_attempt() -> None:
    # A session that never opens is the outage signal the failure floor counts — skipping it on the
    # final attempt would report a wiped-out chunk as a clean success.
    issue = _issue(1)
    with (
        _chunk_context(issues=[issue], done={}),
        patch(f"{_MODULE}.persist_verdict", MagicMock(return_value=True)),
        patch(f"{_MODULE}.start_sandbox_session", AsyncMock(side_effect=RuntimeError("sandbox down"))),
        patch(f"{_MODULE}.end_sandbox_session", AsyncMock()) as mock_end,
    ):
        with pytest.raises(RuntimeError):
            await _env(attempt=VALIDATION_MAX_ATTEMPTS).run(validate_chunk_activity, _input([issue]))

    mock_end.assert_not_awaited()
