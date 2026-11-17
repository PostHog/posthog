# Knowledge writer

PostHog AI, the MCP server, agent evals, and every person or agent on posthog.com read the same docs, but those docs only change when someone remembers to change them.
The knowledge writer takes an input, such as a merged PR, decides whether a docs page needs to change, and opens the docs PR itself.
It is an internal tool for now: it writes posthog.com docs for changes merged into PostHog repositories, and runs in one PostHog project per deployment.

## Who it serves

The primary user is the product engineer who merged a user-facing PR.
They own the feature but rarely the docs page, so the page stays wrong until someone notices.

- Happy when: a docs PR shows up within 1 hour of the merge, the diff is small and right enough to approve in under 5 minutes, and PRs with no user impact never ping them.
- Unhappy when: refactors and test-only PRs get docs PRs, or a draft edits the wrong page or describes behavior the code doesn't have. Hallucinations are the worst failure.
- Measured by: docs PR approve rate, time to approve, and how often the judge says a merge needs docs when it doesn't.
- Failure modes: docs PRs that never get resolved, and developers spammed with PRs.

Secondary readers gain only when that engineer approves:

- PostHog AI and the MCP server answer from the docs, so they should describe a feature correctly on the day it ships.
- Agent evals score the harness, model, MCP, and codebase against the docs. An eval should fail because the agent was wrong, never because a page was a week behind.
- People and agents on posthog.com should find a page that matches the product in front of them.

## Any docs repository

The writer is meant to work on any docs repository, whatever builds it.
It will have no per-framework adapters: a repository will name its nav and redirect files, and one generic check will refuse any edit there that doesn't point at a page the branch changed.
Neither the repository config nor that check is built yet, so for now publish refuses a branch that changes any file outside `KNOWLEDGE_WRITER_DOCS_PATHS`.

## Settings

- `KNOWLEDGE_WRITER_TEAM_ID`, `KNOWLEDGE_WRITER_USER_ID` and `KNOWLEDGE_WRITER_DOCS_REPOSITORY` configure the one writer. `writer_settings()` in `backend/settings.py` reads them, and nothing runs while any of them is unset. The merge check also reads `KNOWLEDGE_WRITER_DOCS_REPOSITORY` through `docs_source()`, with `KNOWLEDGE_WRITER_DOCS_SITEMAP_URL` and `KNOWLEDGE_WRITER_DOCS_URL_PREFIX` for the published pages.
- `KNOWLEDGE_WRITER_DOCS_PATHS` lists the folders of the docs repository a writer branch may change, comma-separated. Unset, publish uses the docs folder the merge check found by matching sitemap pages to files in the docs repository, and `contents/docs/` when it found none. Publish refuses a branch that changes any other path, except a companion edit.
- Turning it into a customer feature means replacing `writer_settings()` with a team-scoped model and triggering from the GitHub App webhook, since a customer can't add a workflow and a secret to every repository.

## Not a security check

The knowledge writer is not a security check.
It assumes what it reads, merged pull requests and their discussion, has already been through a review that would have caught obvious problems.
So every input that arrives through GitHub is a merged pull request, never an open one.
It still takes basic measures: a token scoped to the docs repository, a branch the server issues, the path check below, and prompt markers around untrusted text.
It does not claim to detect or stop a bad actor, and it never runs or validates the code in a page it writes.
Whether a docs page is safe to build is the docs repository's call.

## Review before merge

During the internal rollout, an engineer reviews every writer pull request before it merges, and that review is the control the writer relies on.
Do not auto-merge a writer pull request yet.
Auto-merge is the goal once approve rate shows the drafts can be trusted, so the publish checks are built to hold without a reviewer, and a hole in them is a bug today.

Publish checks the branch once, when the run finishes: it must be the branch the server issued, and it may only change files under the docs folders, plus edits to the companion files in `COMPANION_PATHS` (`vercel.json` and `src/navs/index.js`) when the branch adds, removes or renames a page. Every changed nav line must be data only: brackets, keys, and string, number or boolean values, and every changed `url`, `to`, `href` or `link` value must point at a changed page. In `vercel.json` only `redirects` may change, the order of the other redirects must stay the same, and each changed redirect must have a literal source, stay on the site and name a changed page. Without these edits a branch could not add, move or remove a page. Any other file is refused.
A push that arrives after that check is not checked again, so it reaches the pull request and shows up in its diff for the reviewer.
Until auto-merge, the checks are a second layer under the review, not a replacement for it.

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
2. Launch. Turn on `knowledge-writer-agent-launch` and keep `knowledge-writer-open-prs` off. A `needs_docs` verdict starts a writer run whose finished draft is captured as a `knowledge_writer draft` event (outcome `logged`) with no pull request. Its branch stays on the docs repository, and the event's `compare_url` opens the draft as a diff on GitHub. Read those drafts before stage 3.
3. Open pull requests. Turn on `knowledge-writer-open-prs`. A finished run opens a draft pull request on `KNOWLEDGE_WRITER_DOCS_REPOSITORY`, held to `DAILY_RUN_CAP` and `OPEN_PULL_REQUEST_CAP` in `backend/logic/caps.py`. Check that runs finish with a pushed branch and a draft pull request, that no task carries a `knowledge_writer_pull_request_failure` state entry, and which `WriterCapReached` alerts error tracking shows.

To back out, turn off `knowledge-writer-open-prs` to stop opening pull requests, or `knowledge-writer-agent-launch` to stop new runs, which still lets runs already going publish.
Turn off `knowledge-writer` to stop everything, publishing included.
