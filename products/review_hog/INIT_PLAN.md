# Plan: Replace CodeExecutor with Sandbox Calls

## Context
Moving review_hog into PostHog codebase. Replace `CodeExecutor` (runs Claude Code SDK / Codex CLI locally) with sandbox executor (spawns sandbox agents via Task/Temporal, polls S3 logs).

## Key decisions
- Single combined prompt: branch checkout instructions + system prompt + user prompt
- `project_dir` removed from all signatures — sandbox repo is at `/tmp/workspace/repos/posthog/posthog`
- `prepare_code_context()` still useful (generates `@filename#L1-10` references)
- `MAX_CONCURRENT_SANDBOXES = 5` (docker container limit)
- Output flow: sandbox returns text -> extract JSON locally -> Pydantic validate -> save to `reviews/` dir
- Full S3 logs saved locally per run for debugging
- Entry point: Django management command (`--pr-url` only, no `--project-dir`)

## Files to delete
- `products/review_hog/backend/reviewer/llm/code.py` — replaced by sandbox executor

## Files to create

### 1. `sandbox/code_context.py`
- Move `prepare_code_context()` here (from `llm/code.py`)
- Keep the `PRFile` import it needs

### 2. `sandbox/__init__.py`
- Empty init

### 3. `sandbox/executor.py`
- New `run_sandbox_review()` async function:
  - Combines: branch checkout instructions + system prompt + user prompt into a single string
  - Calls `run_review()` from `runner.py`
  - Extracts JSON from returned text via `extract_json_from_text()`
  - Validates with the Pydantic model
  - Saves validated JSON to `output_path`
  - Saves full logs to a debug file (`_logs.txt` alongside output)
  - Returns `True`/`False`
- Semaphore with `MAX_CONCURRENT_SANDBOXES = 5`

### 4. `management/commands/run_review.py`
- Django management command
- Takes `--pr-url` argument (no `--project-dir`)
- Calls `run.py:main()` with the PR URL

### 5. `management/__init__.py` and `management/commands/__init__.py`

## Files to modify

### 6. `sandbox/runner.py`
- Modify `run_review()` to return `tuple[str, str]` — `(last_message, full_log_content)`
- Modify `_poll_until_done()` to also capture and return full log content
- Modify `_check_logs()` to also return the raw log string

### 7. `run.py`
- Remove `--project-dir` argument and `switch_to_pr_branch()` call
- Add `branch` parameter (from `pr_metadata.head_branch`) passed to all tool functions
- Change `review_dir` to be relative to the review_hog product directory
- Keep `main()` async, make it callable from management command

### 8. `tools/split_pr_into_chunks.py`
- Replace `CodeExecutor` import with `run_sandbox_review` from `sandbox/executor.py`
- Remove `project_dir` param, add `branch` param
- Call `run_sandbox_review()` instead of `CodeExecutor(...).run_code()`

### 9. `tools/chunk_analysis.py`
- Same pattern: replace `CodeExecutor` with `run_sandbox_review`
- Replace `prepare_code_context` import to point to `sandbox/code_context.py`
- Remove `project_dir`, add `branch`

### 10. `tools/issues_review.py`
- Same pattern as above

### 11. `tools/issue_deduplicator.py`
- Same pattern as above

### 12. `tools/issue_validation.py`
- Same pattern as above

### 13. `constants.py`
- Remove `MAX_CONCURRENT_CODE_RUNS_CODEX` and `MAX_CONCURRENT_CODE_RUNS_CLAUDE`
- Add `MAX_CONCURRENT_SANDBOXES = 5`

## Not touching
- `prepare_validation_markdown.py` — doesn't use `CodeExecutor`
- `github_meta.py` — `switch_to_pr_branch()` stays but won't be called from `run.py`
- Prompt templates (`.jinja` files) — unchanged
- Pydantic models — unchanged
- Tests — need updating separately (they mock `CodeExecutor.run_code` extensively)

## Flow summary (before -> after)
```
BEFORE:
  CLI --project-dir -> switch_to_pr_branch() locally -> CodeExecutor(prompt, system_prompt, project_dir) -> Claude Code SDK/Codex -> extract JSON -> validate -> save file

AFTER:
  Management command -> run_sandbox_review(prompt, system_prompt, branch) -> runner.run_review(combined_prompt, branch) -> Sandbox/Temporal -> poll S3 -> extract JSON locally -> validate -> save file + save logs
```
