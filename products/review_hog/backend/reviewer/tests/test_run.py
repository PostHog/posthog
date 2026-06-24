"""Tests for the main run.py orchestration."""

from collections.abc import Generator

import pytest
from unittest.mock import AsyncMock, Mock, patch

from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList
from products.review_hog.backend.reviewer.run import main

_RUN = "products.review_hog.backend.reviewer.run"


@pytest.fixture
def mock_pipeline(expected_chunks: ChunksList) -> Generator[dict[str, Mock]]:
    # Stub every collaborator main() calls. Pipeline state is threaded in-process and persisted via DB
    # helpers — the real round-trip lives in test_persistence.py, so here the persistence boundary is
    # mocked to keep the wiring test DB-free and fast.
    with (
        patch(f"{_RUN}.PRParser") as mock_parser_class,
        patch(f"{_RUN}.PRFetcher") as mock_fetcher_class,
        patch(f"{_RUN}.generate_all_schemas") as mock_schemas,
        patch(f"{_RUN}.split_pr_into_chunks", AsyncMock(return_value=expected_chunks)) as mock_split,
        patch(f"{_RUN}.analyze_chunks", AsyncMock(return_value={})) as mock_analyze,
        patch(f"{_RUN}.review_chunks", AsyncMock(return_value={})) as mock_review,
        patch(f"{_RUN}.combine_issues", Mock(return_value=[])) as mock_combine,
        patch(f"{_RUN}.clean_issues", Mock(return_value=[])) as mock_clean,
        patch(f"{_RUN}.deduplicate_issues", AsyncMock(return_value=[])) as mock_deduplicate,
        patch(f"{_RUN}.validate_issues", AsyncMock(return_value={})) as mock_validate,
        patch(f"{_RUN}.build_review_body", Mock(return_value="# body")) as mock_build_body,
        patch(f"{_RUN}.publish_review", Mock(return_value=None)) as mock_publish,
        patch(f"{_RUN}.bind_sandbox_identity", AsyncMock(return_value=None)) as mock_bind,
        patch(f"{_RUN}.upsert_review_report", Mock(return_value="report-1")) as mock_upsert,
        patch(f"{_RUN}.persist_commit_snapshot", Mock(return_value=True)) as mock_snapshot,
        patch(f"{_RUN}.persist_findings", Mock(return_value=0)) as mock_persist_findings,
        patch(f"{_RUN}.persist_verdicts", Mock(return_value=0)) as mock_persist_verdicts,
        patch(f"{_RUN}.finalize_review_report", Mock(return_value=None)) as mock_finalize,
    ):
        yield {
            "parser_class": mock_parser_class,
            "fetcher_class": mock_fetcher_class,
            "schemas": mock_schemas,
            "split": mock_split,
            "analyze": mock_analyze,
            "review": mock_review,
            "combine": mock_combine,
            "clean": mock_clean,
            "deduplicate": mock_deduplicate,
            "validate": mock_validate,
            "build_body": mock_build_body,
            "publish": mock_publish,
            "bind": mock_bind,
            "upsert": mock_upsert,
            "snapshot": mock_snapshot,
            "persist_findings": mock_persist_findings,
            "persist_verdicts": mock_persist_verdicts,
            "finalize": mock_finalize,
        }


def _wire_pr_data(
    mocks: dict[str, Mock],
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    pr_files: list[PRFile],
    *,
    owner: str = "owner",
    repo: str = "repo",
    pr_number: int = 123,
    diff: str = "diff str",
) -> None:
    mock_parser = Mock()
    mock_parser.parse_github_pr_url.return_value = {"owner": owner, "repo": repo, "pr_number": pr_number}
    mocks["parser_class"].return_value = mock_parser

    mock_fetcher = Mock()
    # New fetch contract returns the reviewed diff as the 4th element.
    mock_fetcher.fetch_pr_data.return_value = (pr_metadata, pr_comments, pr_files, diff)
    mocks["fetcher_class"].return_value = mock_fetcher


@pytest.mark.asyncio
async def test_invalid_pr_url_raises(mock_pipeline: dict[str, Mock]) -> None:
    mock_parser = Mock()
    mock_parser.parse_github_pr_url.side_effect = ValueError("Invalid GitHub PR URL format")
    mock_pipeline["parser_class"].return_value = mock_parser

    with pytest.raises(ValueError, match="Invalid GitHub PR URL format"):
        await main("not-a-valid-url", team_id=1, user_id=1)


@pytest.mark.asyncio
async def test_fetch_error_propagates(mock_pipeline: dict[str, Mock]) -> None:
    mock_parser = Mock()
    mock_parser.parse_github_pr_url.return_value = {"owner": "owner", "repo": "repo", "pr_number": 123}
    mock_pipeline["parser_class"].return_value = mock_parser

    mock_fetcher = Mock()
    mock_fetcher.fetch_pr_data.side_effect = Exception("GitHub API error")
    mock_pipeline["fetcher_class"].return_value = mock_fetcher

    with pytest.raises(Exception, match="GitHub API error"):
        await main("https://github.com/owner/repo/pull/123", team_id=1, user_id=1)


@pytest.mark.asyncio
async def test_wiring_threads_identity_diff_and_body(
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    pr_files: list[PRFile],
    mock_pipeline: dict[str, Mock],
) -> None:
    _wire_pr_data(mock_pipeline, pr_metadata, pr_comments, pr_files)

    await main("https://github.com/owner/repo/pull/123", team_id=7, user_id=9)

    # Explicit team/user reach the sandbox identity bind; team_id + repository open the report.
    mock_pipeline["bind"].assert_awaited_once_with(team_id=7, user_id=9)
    mock_pipeline["upsert"].assert_called_once()
    upsert_kwargs = mock_pipeline["upsert"].call_args.kwargs
    assert upsert_kwargs["team_id"] == 7
    assert upsert_kwargs["repository"] == "owner/repo"

    # The reviewed diff from fetch flows into the snapshot, not just metadata.
    assert mock_pipeline["snapshot"].call_args.kwargs["diff"] == "diff str"

    # The report_id from upsert (not the repository string) threads into every persist call.
    for key in ["snapshot", "persist_findings", "persist_verdicts", "finalize"]:
        kwargs = mock_pipeline[key].call_args.kwargs
        assert kwargs["team_id"] == 7, f"{key} got the wrong team_id"
        assert kwargs["report_id"] == "report-1", f"{key} got the wrong report_id"

    # The built body is what gets finalized onto the report.
    assert mock_pipeline["finalize"].call_args.kwargs["body_markdown"] == "# body"


@pytest.mark.asyncio
async def test_publish_skipped_when_disabled(
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    pr_files: list[PRFile],
    mock_pipeline: dict[str, Mock],
) -> None:
    _wire_pr_data(mock_pipeline, pr_metadata, pr_comments, pr_files)

    # PUBLISH_REVIEW_ENABLED defaults False, so the GitHub publish step must not run.
    await main("https://github.com/owner/repo/pull/123", team_id=1, user_id=1)

    mock_pipeline["publish"].assert_not_called()


@pytest.mark.asyncio
async def test_publish_invoked_when_enabled(
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    pr_files: list[PRFile],
    mock_pipeline: dict[str, Mock],
) -> None:
    _wire_pr_data(mock_pipeline, pr_metadata, pr_comments, pr_files)

    with patch(f"{_RUN}.PUBLISH_REVIEW_ENABLED", True):
        await main("https://github.com/owner/repo/pull/123", team_id=1, user_id=1)

    # Publish is DB-driven: report rows supply body + comments; pr_files map line positions.
    mock_pipeline["publish"].assert_called_once()
    publish_kwargs = mock_pipeline["publish"].call_args.kwargs
    assert publish_kwargs["team_id"] == 1
    assert publish_kwargs["report_id"] == "report-1"
    assert publish_kwargs["pr_files"] is pr_files
