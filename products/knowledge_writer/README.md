# Knowledge writer

An internal tool for now: it opens posthog.com docs pull requests for changes merged into PostHog repositories, and runs in one PostHog project per deployment.

- `KNOWLEDGE_WRITER_TEAM_ID`, `KNOWLEDGE_WRITER_USER_ID` and `KNOWLEDGE_WRITER_DOCS_REPOSITORY` configure the one writer. `writer_settings()` in `backend/settings.py` is their only reader, and nothing runs while any of them is unset.
- `KNOWLEDGE_WRITER_DOCS_PATHS` lists the folders of the docs repository a writer branch may change, comma-separated, and defaults to `contents/docs/`. Set it when the docs live elsewhere, because publish refuses a branch that changes any other path.
- Turning it into a customer feature means replacing `writer_settings()` with a team-scoped model and triggering from the GitHub App webhook, since a customer can't add a workflow and a secret to every repository.

## Not a security check

The knowledge writer is not a security check.
It assumes what it reads, merged pull requests and their discussion, has already been through a review that would have caught obvious problems.
So every input that arrives through GitHub is a merged pull request, never an open one.
It still takes basic measures: a token scoped to the docs repository, a branch the server issues, the path check below, and prompt markers around untrusted text.
It does not claim to detect or stop a bad actor, and it never runs or validates the code in a page it writes.
Whether a docs page is safe to build is the docs repository's call.

## Review before merge

A person reviews every writer pull request before it merges, and that review is the control the writer relies on.
Never auto-merge a writer pull request.

Publish checks the branch once, when the run finishes: it must be the branch the server issued, and it may only change files under `KNOWLEDGE_WRITER_DOCS_PATHS` (default `contents/docs/`).
A push that arrives after that check is not checked again, so it reaches the pull request and shows up in its diff for the reviewer.
The checks are a second layer under the review, not a replacement for it.

## Rollout

Every gate below fails closed without an error, so a missing one looks like a quiet day of merges rather than a failure.
Check each one before reading silence as "no docs needed".

Production needs, before any stage:

- The settings in the first bullet above, for the writer team.
- A GitHub integration on the writer team for each repository owner it touches: `PostHog`, to read merges, and the owner of `KNOWLEDGE_WRITER_DOCS_REPOSITORY`, to publish. [backend/README.md](backend/README.md) covers how one is picked.
- `GITHUB_APP_SLUG`, without which no open docs pull request counts as the writer's, so joining and the open pull request cap stop working.
- `AI_GATEWAY_URL` and `AI_GATEWAY_API_KEY`, which the merge check's judge needs.
- The `knowledge_writer_merged_pull_requests` webhook consumer and the `knowledge-writer-merge-reconcile-schedule` Temporal schedule, which start the merge checks.

Stages, in order:

1. Shadow. Turn on [`knowledge-writer`](https://us.posthog.com/project/2/feature-flags/1036127), the kill switch, and keep [`knowledge-writer-agent-launch`](https://us.posthog.com/project/2/feature-flags/1036128) off. Every `master` merge gets a `knowledge_writer verdict` event, and intake returns `shadow` for each `needs_docs` one instead of starting a run. Before stage 2, check that verdicts arrive for each merge, that `reason: merge_check_failed` is rare, and that `needs_docs` verdicts name the right pages.
2. Launch. Turn on `knowledge-writer-agent-launch`. A `needs_docs` verdict starts a writer run that opens a draft pull request on `KNOWLEDGE_WRITER_DOCS_REPOSITORY`, held to `DAILY_RUN_CAP` and `OPEN_PULL_REQUEST_CAP` in `backend/logic/caps.py`. Check that runs finish with a pushed branch and a draft pull request, that no task carries a `knowledge_writer_pull_request_failure` state entry, and which `WriterCapReached` alerts error tracking shows.

To back out, turn off `knowledge-writer-agent-launch` to stop new runs, which still lets runs already going open their pull requests.
Turn off `knowledge-writer` to stop everything, publishing included.
