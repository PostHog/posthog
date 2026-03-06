import json
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, Literal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from jinja2 import select_autoescape

from products.review_hog.backend.reviewer.models.github_meta import PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.issue_combination import IssueCombination
from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import (
    Issue,
    IssuePriority,
    LineRange,
)
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk, ChunksList, FileInfo
from products.review_hog.backend.reviewer.tests.conftest import create_mock_run_code
from products.review_hog.backend.reviewer.tools.issue_validation import (
    create_validation_task,
    run_validation,
    validate_issues,
)


@pytest.fixture
def sample_chunks_list() -> ChunksList:
    """Create a sample ChunksList for testing."""
    return ChunksList(
        chunks=[
            Chunk(
                chunk_id=1,
                chunk_type="feature",
                files=[
                    FileInfo(filename="src/auth.py"),
                    FileInfo(filename="src/config.py"),
                    FileInfo(filename="src/analyzer.py"),
                ],
                key_changes=["Review authentication flow"],
            ),
            Chunk(
                chunk_id=2,
                chunk_type="bugfix",
                files=[FileInfo(filename="db/migrations/001_add_users.sql")],
                key_changes=["Check foreign key constraints"],
            ),
        ]
    )


@pytest.fixture
def sample_validation_result() -> IssueValidation:
    """Create a sample IssueValidation result."""
    return IssueValidation(
        is_valid=True,
        argumentation="The issue correctly identifies a potential IndexError. Empty list [] is truthy in Python.",
        category="bug",
    )


@pytest.fixture
def mock_run_claude_code_validation(
    sample_validation_result: IssueValidation,
) -> Any:
    """Create a mock for CodeExecutor.run_code that returns IssueValidation."""
    return create_mock_run_code(sample_validation_result)


# mock_prepare_code_context fixture moved to conftest.py


@pytest.fixture
def setup_review_dir_with_issues_found(
    temp_review_dir: Path,
    sample_chunks_list: ChunksList,
) -> Path:
    """Setup review directory with issues_found.json file."""
    # Create chunks.json
    chunks_file = temp_review_dir / "chunks.json"
    chunks_file.write_text(sample_chunks_list.model_dump_json())

    # Create issues_found.json with combined issues from all passes
    combined_issues = IssueCombination(
        issues=[
            Issue(
                id="1-1-1",  # pass-chunk-issue format
                title="SQL Injection vulnerability",
                file="src/auth/login.py",
                lines=[LineRange(start=45, end=50)],
                issue="Direct string concatenation in SQL query",
                suggestion="Use parameterized queries",
                priority=IssuePriority.MUST_FIX,
            ),
            Issue(
                id="2-2-1",  # pass-chunk-issue format
                title="Missing error handling",
                file="db/queries.py",
                lines=[LineRange(start=15, end=20)],
                issue="No exception handling around database operations",
                suggestion="Add try-catch blocks",
                priority=IssuePriority.SHOULD_FIX,
            ),
        ]
    )

    # Write combined issues to issues_found.json
    issues_found_file = temp_review_dir / "issues_found.json"
    issues_found_file.write_text(combined_issues.model_dump_json(indent=2))

    return temp_review_dir


class TestCreateValidationTask:
    """Test create_validation_task function."""

    @pytest.mark.asyncio
    async def test_create_validation_task_success(
        self,
        sample_issue: Issue,
        pr_metadata: PRMetadata,
        pr_files: list[PRFile],
        sample_chunks_list: ChunksList,
        temp_review_dir: Path,
        temp_project_dir: Path,
        mock_prepare_code_context: MagicMock,
    ) -> None:
        """Test successful creation of validation task."""
        # Setup directories
        validation_prompts_dir = temp_review_dir / "validation" / "prompts"
        validation_summaries_dir = temp_review_dir / "validation" / "summaries"
        validation_prompts_dir.mkdir(parents=True, exist_ok=True)
        validation_summaries_dir.mkdir(parents=True, exist_ok=True)

        # Load actual schema and template
        prompts_dir = Path(__file__).parent.parent / "prompts" / "issue_validation"
        with (prompts_dir / "schema.json").open() as f:
            schema = f.read()

        from jinja2 import Environment, FileSystemLoader

        env = Environment(loader=FileSystemLoader(prompts_dir), autoescape=select_autoescape())
        template = env.get_template("prompt.jinja")

        with (
            patch("app.llm.code.prepare_code_context", mock_prepare_code_context),
            patch("app.tools.issue_validation.run_validation", return_value=True),
        ):
            result = await create_validation_task(
                template=template,
                issue=sample_issue,
                chunk_index=1,
                issue_index=1,
                validation_prompts_dir=validation_prompts_dir,
                validation_summaries_dir=validation_summaries_dir,
                schema=schema,
                pr_metadata=pr_metadata,
                chunk_data=sample_chunks_list.chunks[0].model_dump(),
                pr_files=pr_files,
                project_dir=str(temp_project_dir),
            )

            assert result is True

            # Check prompt file was created
            prompt_file = validation_prompts_dir / "chunk-1-issue-1-validation-prompt.md"
            assert prompt_file.exists()

            # Verify prompt content
            prompt_content = prompt_file.read_text()
            assert "@src/analyzer.py" in prompt_content  # Code context
            assert sample_issue.title in prompt_content
            assert "pr_issue_validation_instructions" in prompt_content
            assert schema in prompt_content

    @pytest.mark.asyncio
    async def test_create_validation_task_skip_existing(
        self,
        sample_issue: Issue,
        pr_metadata: PRMetadata,
        pr_files: list[PRFile],
        sample_chunks_list: ChunksList,
        temp_review_dir: Path,
        sample_validation_result: IssueValidation,
    ) -> None:
        """Test that existing validations are skipped."""
        # Setup directories
        validation_prompts_dir = temp_review_dir / "validation" / "prompts"
        validation_summaries_dir = temp_review_dir / "validation" / "summaries"
        validation_prompts_dir.mkdir(parents=True, exist_ok=True)
        validation_summaries_dir.mkdir(parents=True, exist_ok=True)

        # Create existing validation file
        output_file = validation_summaries_dir / "chunk-1-issue-1-validation-summary.json"
        output_file.write_text(sample_validation_result.model_dump_json())

        # Load template and schema
        prompts_dir = Path(__file__).parent.parent / "prompts" / "issue_validation"
        with (prompts_dir / "schema.json").open() as f:
            schema = f.read()

        from jinja2 import Environment, FileSystemLoader

        env = Environment(loader=FileSystemLoader(prompts_dir), autoescape=select_autoescape())
        template = env.get_template("prompt.jinja")

        with patch("app.tools.issue_validation.run_validation") as mock_run:
            result = await create_validation_task(
                template=template,
                issue=sample_issue,
                chunk_index=1,
                issue_index=1,
                validation_prompts_dir=validation_prompts_dir,
                validation_summaries_dir=validation_summaries_dir,
                schema=schema,
                pr_metadata=pr_metadata,
                chunk_data=sample_chunks_list.chunks[0].model_dump(),
                pr_files=pr_files,
                project_dir="/test/project",
            )

            assert result is None  # Should return None for existing validation
            mock_run.assert_not_called()  # Should not run validation

    @pytest.mark.asyncio
    async def test_create_validation_task_no_file_context(
        self,
        pr_metadata: PRMetadata,
        pr_files: list[PRFile],
        sample_chunks_list: ChunksList,
        temp_review_dir: Path,
        temp_project_dir: Path,
    ) -> None:
        """Test validation task creation for issue without file context."""
        # Create issue without file
        issue_no_file = Issue(
            id="1-1",
            title="General code quality issue",
            file="",  # No specific file
            lines=[],
            issue="Inconsistent naming conventions",
            suggestion="Use consistent naming throughout",
            priority=IssuePriority.CONSIDER,  # Add required priority field
        )

        # Setup directories
        validation_prompts_dir = temp_review_dir / "validation" / "prompts"
        validation_summaries_dir = temp_review_dir / "validation" / "summaries"
        validation_prompts_dir.mkdir(parents=True, exist_ok=True)
        validation_summaries_dir.mkdir(parents=True, exist_ok=True)

        # Load template and schema
        prompts_dir = Path(__file__).parent.parent / "prompts" / "issue_validation"
        with (prompts_dir / "schema.json").open() as f:
            schema = f.read()

        from jinja2 import Environment, FileSystemLoader

        env = Environment(loader=FileSystemLoader(prompts_dir), autoescape=select_autoescape())
        template = env.get_template("prompt.jinja")

        with patch("app.tools.issue_validation.run_validation", return_value=True):
            result = await create_validation_task(
                template=template,
                issue=issue_no_file,
                chunk_index=1,
                issue_index=1,
                validation_prompts_dir=validation_prompts_dir,
                validation_summaries_dir=validation_summaries_dir,
                schema=schema,
                pr_metadata=pr_metadata,
                chunk_data=sample_chunks_list.chunks[0].model_dump(),
                pr_files=pr_files,
                project_dir=str(temp_project_dir),
            )

            assert result is True

            # Check prompt file was created without code context
            prompt_file = validation_prompts_dir / "chunk-1-issue-1-validation-prompt.md"
            assert prompt_file.exists()
            prompt_content = prompt_file.read_text()
            # Should have empty code context when no file is specified
            assert "<pr_issue_validation_instructions>" in prompt_content
            # When there's no file, there should be no @ references in the content
            assert "@" not in prompt_content.split("<pr_issue_validation_instructions>")[0]


class TestRunValidation:
    """Test run_validation function."""

    @pytest.mark.asyncio
    async def test_run_validation_success(
        self,
        temp_review_dir: Path,
        temp_project_dir: Path,
        mock_run_claude_code_validation: AsyncMock,
    ) -> None:
        """Test successful validation run."""
        output_path = temp_review_dir / "test-validation.json"
        prompt = "Test validation prompt"

        with patch(
            "app.tools.issue_validation.CodeExecutor.run_code",
            mock_run_claude_code_validation,
        ):
            result = await run_validation(
                prompt=prompt,
                output_path=output_path,
                project_dir=str(temp_project_dir),
                chunk_index=1,
                issue_index=1,
            )

            assert result is True
            assert output_path.exists()

            # Verify output is valid IssueValidation
            with output_path.open() as f:
                validation = IssueValidation.model_validate_json(f.read())
            assert validation.is_valid is True
            assert validation.category == "bug"

    @pytest.mark.asyncio
    async def test_run_validation_failure(
        self,
        temp_review_dir: Path,
        temp_project_dir: Path,
        mock_run_claude_code_failure: AsyncMock,
    ) -> None:
        """Test handling of validation failure."""
        output_path = temp_review_dir / "test-validation.json"
        prompt = "Test validation prompt"

        with patch(
            "app.tools.issue_validation.CodeExecutor.run_code",
            mock_run_claude_code_failure,
        ):
            result = await run_validation(
                prompt=prompt,
                output_path=output_path,
                project_dir=str(temp_project_dir),
                chunk_index=1,
                issue_index=1,
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_run_validation_exception_handling(self, temp_review_dir: Path, temp_project_dir: Path) -> None:
        """Test exception handling in run_validation."""
        output_path = temp_review_dir / "test-validation.json"
        prompt = "Test validation prompt"

        async def mock_exception(self: Any) -> bool:  # noqa: ARG001
            raise Exception("Unexpected error")

        with patch("app.tools.issue_validation.CodeExecutor.run_code", mock_exception):
            result = await run_validation(
                prompt=prompt,
                output_path=output_path,
                project_dir=str(temp_project_dir),
                chunk_index=1,
                issue_index=1,
            )

            assert result is False


class TestValidateIssues:
    """Test validate_issues function."""

    @pytest.mark.asyncio
    async def test_validate_issues_from_combined_file(
        self,
        sample_chunks_list: ChunksList,
        pr_metadata: PRMetadata,
        pr_files: list[PRFile],
        setup_review_dir_with_issues_found: Path,
        temp_project_dir: Path,
        mock_run_claude_code_validation: AsyncMock,
        mock_prepare_code_context: MagicMock,
    ) -> None:
        """Test validation of issues from combined issues_found.json file."""
        with (
            patch("app.llm.code.prepare_code_context", mock_prepare_code_context),
            patch(
                "app.tools.issue_validation.CodeExecutor.run_code",
                mock_run_claude_code_validation,
            ),
        ):
            await validate_issues(
                chunks_data=sample_chunks_list,
                pr_metadata=pr_metadata,
                pr_files=pr_files,
                review_dir=setup_review_dir_with_issues_found,
                project_dir=str(temp_project_dir),
            )

            # Check validation output files were created for different passes
            pass1_validation = setup_review_dir_with_issues_found / "pass1_results" / "validation" / "summaries"
            pass2_validation = setup_review_dir_with_issues_found / "pass2_results" / "validation" / "summaries"

            # Check that validation directories were created
            assert pass1_validation.exists() or pass2_validation.exists()

            # Check that validation files were created
            all_validation_files = []
            if pass1_validation.exists():
                all_validation_files.extend(list(pass1_validation.glob("*.json")))
            if pass2_validation.exists():
                all_validation_files.extend(list(pass2_validation.glob("*.json")))

            assert len(all_validation_files) > 0

    @pytest.mark.asyncio
    async def test_validate_issues_no_issues_found_file(
        self,
        sample_chunks_list: ChunksList,
        pr_metadata: PRMetadata,
        pr_files: list[PRFile],
        temp_review_dir: Path,
        temp_project_dir: Path,
    ) -> None:
        """Test validation when no issues_found.json file exists."""
        # Don't create issues_found.json file

        # Should raise FileNotFoundError or handle gracefully
        with pytest.raises(FileNotFoundError):
            await validate_issues(
                chunks_data=sample_chunks_list,
                pr_metadata=pr_metadata,
                pr_files=pr_files,
                review_dir=temp_review_dir,
                project_dir=str(temp_project_dir),
            )

    @pytest.mark.asyncio
    async def test_validate_issues_empty_issues_found_file(
        self,
        sample_chunks_list: ChunksList,
        pr_metadata: PRMetadata,
        pr_files: list[PRFile],
        temp_review_dir: Path,
        temp_project_dir: Path,
    ) -> None:
        """Test validation when issues_found.json is empty."""
        # Create empty issues_found.json file
        issues_found_file = temp_review_dir / "issues_found.json"
        empty_combination = IssueCombination(issues=[])
        issues_found_file.write_text(empty_combination.model_dump_json(indent=2))

        await validate_issues(
            chunks_data=sample_chunks_list,
            pr_metadata=pr_metadata,
            pr_files=pr_files,
            review_dir=temp_review_dir,
            project_dir=str(temp_project_dir),
        )

        # Should complete without errors, check if any actual validation files were created
        validation_files = list(temp_review_dir.glob("**/validation/summaries/*.json"))
        assert len(validation_files) == 0

    @pytest.mark.asyncio
    async def test_validate_issues_batch_processing(
        self,
        pr_metadata: PRMetadata,
        pr_files: list[PRFile],
        temp_review_dir: Path,
        temp_project_dir: Path,
        mock_run_claude_code_validation: Callable[[Any], Coroutine[Any, Any, bool]],
        mock_prepare_code_context: str,
    ) -> None:
        """Test that issues are processed in batches."""
        # Create a ChunksList with many chunks
        chunks = []
        for i in range(5):
            chunks.append(
                Chunk(
                    chunk_id=i + 1,
                    chunk_type="feature",
                    files=[FileInfo(filename=f"file{i}.py")],
                    key_changes=[],
                )
            )
        chunks_list = ChunksList(chunks=chunks)

        # Create issues_found.json with many issues (to test batching)
        all_issues = []
        for i in range(5):
            # Create multiple issues per chunk
            for j in range(3):  # 3 issues per chunk
                all_issues.append(
                    Issue(
                        id=f"1-{i + 1}-{j}",  # pass-chunk-issue format
                        title=f"Issue {j} in chunk {i + 1}",
                        file=f"file{i}.py",
                        lines=[LineRange(start=j * 10, end=j * 10 + 5)],
                        issue=f"Problem {j}",
                        suggestion=f"Fix {j}",
                        priority=IssuePriority.MUST_FIX,
                    )
                )

        # Write all issues to issues_found.json
        issues_found_file = temp_review_dir / "issues_found.json"
        issue_combination = IssueCombination(issues=all_issues)
        issues_found_file.write_text(issue_combination.model_dump_json(indent=2))

        call_count = 0

        async def counting_mock(self: Any) -> bool:
            nonlocal call_count
            call_count += 1
            # Use the create_mock_run_code function's logic
            return await mock_run_claude_code_validation(self)

        with (
            patch(
                "app.tools.issue_validation.prepare_code_context",
                return_value=mock_prepare_code_context,
            ),
            patch("app.tools.issue_validation.CodeExecutor.run_code", counting_mock),
        ):
            await validate_issues(
                chunks_data=chunks_list,
                pr_metadata=pr_metadata,
                pr_files=pr_files,
                review_dir=temp_review_dir,
                project_dir=str(temp_project_dir),
            )

            # Should have processed all 15 issues (5 chunks * 3 issues)
            assert call_count == 15

            # Check validation files were created
            validation_files = list(temp_review_dir.glob("**/validation/summaries/*.json"))
            assert len(validation_files) == 15


class TestValidateIssuesEndToEnd:
    """End-to-end test for the complete validation flow."""

    @pytest.mark.asyncio
    async def test_validate_issues_e2e(
        self,
        pr_metadata: PRMetadata,
        pr_files: list[PRFile],
        temp_review_dir: Path,
        temp_project_dir: Path,
        mock_prepare_code_context: MagicMock,
    ) -> None:
        """Test the complete validation flow from PR data to validation outputs."""
        # Setup comprehensive test data
        chunks_list = ChunksList(
            chunks=[
                Chunk(
                    chunk_id=1,
                    chunk_type="feature",
                    files=[
                        FileInfo(filename="auth.py"),
                        FileInfo(filename="config.py"),
                    ],
                    key_changes=["OAuth flow"],
                ),
                Chunk(
                    chunk_id=2,
                    chunk_type="refactoring",
                    files=[FileInfo(filename="db.py")],
                    key_changes=["Schema"],
                ),
            ]
        )

        # Create issues from multiple passes to test comprehensive validation
        all_issues = []
        for pass_num in range(1, 4):
            for chunk in chunks_list.chunks:
                if pass_num == 1:
                    all_issues.append(
                        Issue(
                            id=f"{pass_num}-{chunk.chunk_id}-1",  # pass-chunk-issue format
                            title=f"Critical issue in pass {pass_num} chunk {chunk.chunk_id}",
                            file=chunk.files[0].filename if chunk.files else "unknown.py",
                            lines=[LineRange(start=10, end=20)],
                            issue=f"Pass {pass_num} found critical problem",
                            suggestion="Fix immediately",
                            priority=IssuePriority.MUST_FIX,
                        )
                    )
                elif pass_num == 2:
                    all_issues.append(
                        Issue(
                            id=f"{pass_num}-{chunk.chunk_id}-2",  # pass-chunk-issue format
                            title=f"Should fix in pass {pass_num} chunk {chunk.chunk_id}",
                            file=chunk.files[0].filename if chunk.files else "unknown.py",
                            lines=[LineRange(start=30, end=40)],
                            issue=f"Pass {pass_num} found issue",
                            suggestion="Consider fixing",
                            priority=IssuePriority.SHOULD_FIX,
                        )
                    )
                elif pass_num == 3:
                    all_issues.append(
                        Issue(
                            id=f"{pass_num}-{chunk.chunk_id}-3",  # pass-chunk-issue format
                            title=f"Consider in pass {pass_num} chunk {chunk.chunk_id}",
                            file=chunk.files[0].filename if chunk.files else "unknown.py",
                            lines=[LineRange(start=50, end=60)],
                            issue=f"Pass {pass_num} suggestion",
                            suggestion="Nice to have",
                            priority=IssuePriority.CONSIDER,
                        )
                    )

        # Write all issues to issues_found.json
        issues_found_file = temp_review_dir / "issues_found.json"
        issue_combination = IssueCombination(issues=all_issues)
        issues_found_file.write_text(issue_combination.model_dump_json(indent=2))

        # Mock validation responses
        validation_results = []

        async def mock_validation(
            self: Any,
        ) -> bool:
            """Create varied validation results."""
            prompt = self.prompt
            output_path = self.output_path
            # Parse issue from prompt to create appropriate validation
            is_valid = "Critical" in prompt  # Critical issues are valid
            if "Critical" in prompt:
                category: (
                    Literal[
                        "bug",
                        "security",
                        "performance",
                        "code_quality",
                        "best_practice",
                        "documentation",
                        "testing",
                        "accessibility",
                        "compatibility",
                    ]
                    | None
                ) = "security"
            elif "Performance" in prompt:
                category = "performance"
            else:
                category = "code_quality"

            validation = IssueValidation(
                is_valid=is_valid,
                argumentation="Analysis of issue based on codebase context",
                category=category,
            )

            with Path(output_path).open("w") as f:
                f.write(json.dumps(validation.model_dump(mode="json"), indent=2))

            validation_results.append(output_path)
            return True

        with (
            patch("app.llm.code.prepare_code_context", mock_prepare_code_context),
            patch(
                "app.tools.issue_validation.CodeExecutor.run_code",
                mock_validation,
            ),
        ):
            await validate_issues(
                chunks_data=chunks_list,
                pr_metadata=pr_metadata,
                pr_files=pr_files,
                review_dir=temp_review_dir,
                project_dir=str(temp_project_dir),
            )

        # Verify all expected validations were created
        total_validations = 0
        for pass_num in range(1, 4):
            pass_dir = temp_review_dir / f"pass{pass_num}_results"
            validation_dir = pass_dir / "validation" / "summaries"
            prompt_dir = pass_dir / "validation" / "prompts"

            if validation_dir.exists():
                validation_files = list(validation_dir.glob("*.json"))
                prompt_files = list(prompt_dir.glob("*.md"))

                # Each validation should have a corresponding prompt
                assert len(validation_files) == len(prompt_files)

                # Verify validation content
                for val_file in validation_files:
                    with val_file.open() as f:
                        validation = IssueValidation.model_validate_json(f.read())

                    # Check validation has required fields
                    assert validation.argumentation
                    assert validation.category in [
                        "bug",
                        "security",
                        "performance",
                        "code_quality",
                        "best_practice",
                        "documentation",
                        "testing",
                        "accessibility",
                        "compatibility",
                        None,
                    ]

                total_validations += len(validation_files)

        # Should have validated all issues (2 chunks * 3 passes * 1 issue per pass = 6)
        assert total_validations == 6

        # Verify prompt files contain expected content
        for pass_num in range(1, 4):
            prompt_dir = temp_review_dir / f"pass{pass_num}_results" / "validation" / "prompts"
            if prompt_dir.exists():
                prompt_files = list(prompt_dir.glob("*.md"))
                for prompt_file in prompt_files:
                    content = prompt_file.read_text()

                    # Check prompt contains required sections
                    assert "<pr_issue_validation_instructions>" in content
                    assert "<pr_context>" in content
                    assert "<pr_current_chunk_context>" in content
                    assert "<output_schema>" in content
                    assert "IssueValidation" in content  # Schema name
