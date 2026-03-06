# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a multi-pass GitHub PR review system that uses sandbox agents to analyze code changes.
The system splits large PRs into logical chunks and performs three sequential review passes focusing on different aspects of code quality.
Each sandbox spawns a Docker container with a fresh checkout of the repository at the PR's branch.

## Key Commands

### Development

- **Run review (Django management command)**: `python manage.py run_review --pr-url <github_pr_url>`
- **Linting**: `ruff check products/review_hog/ --fix && ruff format products/review_hog/`

### Testing

- **Run all tests**: `pytest products/review_hog/backend/reviewer/tests/ -xvs`
- **Run specific test**: `pytest products/review_hog/backend/reviewer/tests/test_<module>.py::test_<function> -xvs`

## Architecture

### Multi-Pass Review System

The system performs three sequential review passes on each PR:

1. **Pass 1 - Logic & Correctness**: Validates business logic, algorithms, data handling
2. **Pass 2 - Contracts & Security**: Ensures API compatibility and security
3. **Pass 3 - Performance & Reliability**: Identifies performance bottlenecks and reliability issues

Each pass shares context with subsequent passes to avoid duplicate findings.

### Core Workflow

1. **PR Data Fetching** (`tools/github_meta.py`): Downloads PR metadata, files, and comments via GitHub API
2. **Chunking** (`tools/split_pr_into_chunks.py`): Splits PR into logical, reviewable chunks using a sandbox agent
3. **Chunk Analysis** (`tools/chunk_analysis.py`): Analyzes each chunk to understand architecture
4. **Issue Review** (`tools/issues_review.py`): Performs multi-pass review on each chunk
5. **Issue Processing Pipeline**:
   - `tools/issue_combination.py`: Combines issues from all passes
   - `tools/issue_cleaner.py`: Filters issues based on PR scope
   - `tools/issue_deduplicator.py`: Removes duplicate issues using a sandbox agent
   - `tools/issue_validation.py`: Validates each issue against actual code
6. **Output Generation** (`tools/prepare_validation_markdown.py`): Creates markdown reports

### Sandbox Execution

All LLM-powered steps run inside sandbox agents via `sandbox/executor.py`:

- **`run_sandbox_review()`**: Combines system prompt + user prompt, sends to `sandbox/runner.py`, extracts JSON from the response, validates with Pydantic, and saves locally.
- **`sandbox/runner.py`**: Creates a Task + TaskRun, triggers a Temporal workflow that spawns a Docker sandbox, polls S3 logs until completion, returns the last agent message and full logs.
- **Branch handling**: Each sandbox prompt is prepended with `git fetch origin <branch> && git checkout <branch>` so the agent works on the correct PR branch.
- **Concurrency**: Limited to `MAX_CONCURRENT_SANDBOXES = 5` via an asyncio semaphore.
- **Code context**: `sandbox/code_context.py` generates `@filename#L1-10` references to focus agents on changed lines.

### Key Design Patterns

- **Pydantic Models**: All data structures use Pydantic for validation and serialization
- **Jinja2 Templates**: All prompts use Jinja templates in `prompts/`
- **Async Processing**: Heavy operations use `asyncio` for concurrent processing
- **Structured Outputs**: Agent responses follow JSON schemas defined in `prompts/*/schema.json`

### Directory Structure

- `backend/reviewer/models/`: Pydantic data models and schema generators
- `backend/reviewer/tools/`: Core processing tools (one per workflow step)
- `backend/reviewer/prompts/`: Jinja2 templates and JSON schemas for agents
- `backend/reviewer/sandbox/`: Sandbox execution layer (`runner.py`, `executor.py`, `code_context.py`)
- `backend/reviewer/utils/`: Utilities (JSON extraction, etc.)
- `backend/reviewer/tests/`: Test suite with fixtures
- `backend/management/commands/`: Django management command entry point
- `reviews/`: Output directory for review results (gitignored), organized by PR number

### Important Files

- `backend/reviewer/run.py`: Main async entry point orchestrating the entire workflow
- `backend/reviewer/sandbox/executor.py`: Sandbox execution wrapper (replaces the old `CodeExecutor`)
- `backend/reviewer/sandbox/runner.py`: Low-level sandbox Task/Temporal integration
- `backend/reviewer/constants.py`: Concurrency limits and other constants

## Testing Approach

- All tools have corresponding test files in `backend/reviewer/tests/test_<tool>.py`
- Tests use fixtures from `backend/reviewer/tests/fixtures/` for consistent test data
- Async functions are tested with `pytest-asyncio`
- Sandbox calls are mocked in tests to avoid spawning real containers

## Code Quality Standards

- Type hints required for all functions
- Maximum line length: 120 characters
- Linting: `ruff check` and `ruff format`
