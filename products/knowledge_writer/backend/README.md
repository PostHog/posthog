# Knowledge writer

- `adapters/`: turn a source event (the docs command, …) into a docs request.
- `logic/intake.py`: caps, section routing, and the start-or-join decision.
- `logic/launch.py`: creates the writer task.
- `logic/pull_requests.py`: opens a draft docs pull request, or comments a joined request's source on the open one.
- `receivers.py`: calls `logic/pull_requests.py` when a writer run finishes.
- `management/commands/knowledge_writer_pr_smoke_test.py`: drives the pull request path against a scratch repository.

## Smoke test against a scratch repository

Set up the dev GitHub App with `python manage.py create_github_app`, following [the sandboxes setup guide](../../../docs/internal/sandboxes-setup-guide.md). What the guide does not cover:

- Run every command inside flox (`flox activate -- …`). Plain `uv` or `python` builds a stray Python 3.14 `.venv` and fails on `SECRET_KEY`, because `DEBUG` is unset.
- On a Coder workspace, forward the callback port before `create_github_app`: `coder port-forward <workspace> --tcp 8019:8019`.
- A fresh database needs `hogli migrations:up`, then `python manage.py setup_dev --no-data`, before `setup_background_agents`.
- Fork `posthog.com` into your own account and install the App on that fork only. The writer picks the GitHub integration whose account matches the repository owner.

Then:

```bash
export KNOWLEDGE_WRITER_TEAM_ID=<team id>
export KNOWLEDGE_WRITER_USER_ID=<user id>
export KNOWLEDGE_WRITER_DOCS_REPOSITORY=<you>/posthog.com
flox activate -- python manage.py knowledge_writer_pr_smoke_test \
  --repo <you>/posthog.com --team-id <team id> [--installation-id <installation id>]
```
