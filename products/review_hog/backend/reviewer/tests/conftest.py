from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from pydantic import BaseModel

from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRMetadata


@pytest.fixture
def pr_metadata() -> PRMetadata:
    fixtures_dir = Path(__file__).parent / "fixtures"
    with (fixtures_dir / "pr_meta.json").open() as f:
        return PRMetadata.model_validate_json(f.read())


@pytest.fixture
def pr_files() -> list[PRFile]:
    fixtures_dir = Path(__file__).parent / "fixtures"
    files = []
    with (fixtures_dir / "pr_files.jsonl").open() as f:
        for line in f:
            if line.strip():
                files.append(PRFile.model_validate_json(line))
    return files


@pytest.fixture
def pr_comments() -> list[PRComment]:
    fixtures_dir = Path(__file__).parent / "fixtures"
    comments = []
    with (fixtures_dir / "pr_comments.jsonl").open() as f:
        for line in f:
            if line.strip():
                comments.append(PRComment.model_validate_json(line))
    return comments


def create_mock_run_sandbox_review(model_instance: BaseModel) -> Callable[..., Awaitable[BaseModel]]:
    # Mocks an LLM executor seam (run_sandbox_review / run_oneshot_review): returns the parsed
    # model the executor would yield.
    async def mock_func(**kwargs: object) -> BaseModel:
        return model_instance

    return mock_func
