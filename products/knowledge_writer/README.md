# Knowledge writer

An internal tool for now: it opens posthog.com docs pull requests for changes merged into PostHog repositories, and runs in one PostHog project per deployment.

- `KNOWLEDGE_WRITER_TEAM_ID`, `KNOWLEDGE_WRITER_USER_ID` and `KNOWLEDGE_WRITER_DOCS_REPOSITORY` configure the one writer. `writer_settings()` in `backend/settings.py` is their only reader, and nothing runs while any of them is unset.
- Turning it into a customer feature means replacing `writer_settings()` with a team-scoped model and triggering from the GitHub App webhook, since a customer can't add a workflow and a secret to every repository.
