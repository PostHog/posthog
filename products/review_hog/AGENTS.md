# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a multi-pass GitHub PR review system that uses Claude AI to analyze code changes. The system splits large PRs into logical chunks and performs three sequential review passes focusing on different aspects of code quality.

## Key Commands

### Development

- **Run main application**: `python -m products.review_hog.backend.reviewer.run --pr-url <github_pr_url> --project-dir <absolute_path>`
- **Linting (ruff/mypy/etc.)**: `pre-commit run --all-files`

### Testing

- **Run all tests**: `pytest -xvs`
- **Run specific test**: `pytest products/review_hog/backend/reviewer/tests/test_<module>.py::test_<function> -xvs`

### Dependencies

- **Install dependencies**: `uv sync`

## Architecture

### Multi-Pass Review System

The system performs three sequential review passes on each PR:

1. **Pass 1 - Logic & Correctness**: Validates business logic, algorithms, data handling
2. **Pass 2 - Contracts & Security**: Ensures API compatibility and security
3. **Pass 3 - Performance & Reliability**: Identifies performance bottlenecks and reliability issues

Each pass shares context with subsequent passes to avoid duplicate findings.

### Core Workflow

1. **PR Data Fetching** (`github_meta.py`): Downloads PR metadata, files, and comments
2. **Chunking** (`split_pr_into_chunks.py`): Splits PR into logical, reviewable chunks using Claude
3. **Chunk Analysis** (`chunk_analysis.py`): Analyzes each chunk to understand architecture
4. **Issue Review** (`issues_review.py`): Performs multi-pass review on each chunk
5. **Issue Processing Pipeline**:
   - `issue_combination.py`: Combines issues from all passes
   - `issue_cleaner.py`: Filters issues based on PR scope
   - `issue_deduplicator.py`: Removes duplicate issues using Claude
   - `issue_validation.py`: Validates each issue against actual code
6. **Output Generation** (`prepare_validation_markdown.py`): Creates markdown reports

### Key Design Patterns

- **Pydantic Models**: All data structures use Pydantic for validation and serialization
- **Jinja2 Templates**: All prompts use Jinja templates in `products/review_hog/backend/reviewer/prompts/`
- **Async Processing**: Heavy operations use `asyncio` for concurrent processing
- **Structured Outputs**: Claude responses follow JSON schemas defined in `products/review_hog/backend/reviewer/prompts/*/schema.json`
- **Token Usage Tracking**: All LLM calls track and report token usage

### Directory Structure

- `products/review_hog/backend/reviewer/models/`: Pydantic data models and schema generators
- `products/review_hog/backend/reviewer/tools/`: Core processing tools (one per workflow step)
- `products/review_hog/backend/reviewer/prompts/`: Jinja2 templates and JSON schemas for Claude
- `products/review_hog/backend/reviewer/llm/`: Claude Code SDK and OpenAI Codex CLI integration
- `products/review_hog/backend/reviewer/tests/`: Comprehensive test suite with fixtures
- `reviews/`: Output directory for review results (gitignored)

### Important Files

- `products/review_hog/backend/reviewer/run.py`: Main entry point orchestrating the entire workflow

## Testing Approach

- All tools have corresponding test files in `products/review_hog/backend/reviewer/tests/test_<tool>.py`
- Tests use fixtures from `products/review_hog/backend/reviewer/tests/fixtures/` for consistent test data
- Async functions are tested with `pytest-asyncio`
- Coding agent calls in tests to avoid rate limits and costs

## Code Quality Standards

- Type hints required for all functions
- Maximum line length: 88 characters
- McCabe complexity limit: 18
- Pre-commit hooks configured for automatic checks
