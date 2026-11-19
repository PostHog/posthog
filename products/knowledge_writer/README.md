# Knowledge writer

An internal tool for now: it opens posthog.com docs pull requests for changes merged into PostHog repositories, and runs in one PostHog project per deployment.

- `KNOWLEDGE_WRITER_TEAM_ID`, `KNOWLEDGE_WRITER_USER_ID` and `KNOWLEDGE_WRITER_DOCS_REPOSITORY` configure the one writer. `writer_settings()` in `backend/settings.py` reads them, and nothing runs while any of them is unset. The merge check also reads `KNOWLEDGE_WRITER_DOCS_REPOSITORY` through `docs_source()`, with `KNOWLEDGE_WRITER_DOCS_SITEMAP_URL` and `KNOWLEDGE_WRITER_DOCS_URL_PREFIX` for the published pages.
- `KNOWLEDGE_WRITER_DOCS_PATHS` lists the folders of the docs repository a writer change may touch, comma-separated. Unset, publish uses the docs folder the merge check found by matching sitemap pages to files in the docs repository, and `contents/docs/` when it found none. Publish refuses a change to any other path, except a companion edit.
- Turning it into a customer feature means replacing `writer_settings()` with a team-scoped model and triggering from the GitHub App webhook, since a customer can't add a workflow and a secret to every repository.

## Not a security check

The knowledge writer is not a security check.
It assumes what it reads, merged pull requests and their discussion, has already been through a review that would have caught obvious problems.
So every input that arrives through GitHub is a merged pull request, never an open one.
It still takes basic measures: a read-only docs token in the sandbox, a commit only the server makes, the path check below, and prompt markers around untrusted text.
It does not claim to detect or stop a bad actor, and it never runs or validates the code in a page it writes.
Whether a docs page is safe to build is the docs repository's call.

## Review before merge

A person reviews every writer pull request before it merges, and that review is the control the writer relies on.
Never auto-merge a writer pull request.
Each pull request asks the source pull request's author to review it: they know the change best, and without the request nobody learns the pull request exists. A bot author gets no request.
A flagged pull request opens as a draft that lists what a reviewer should check first: grounding that did not run, added lines the server could not ground in the source change, edits to existing pages the merge check did not suggest, flagged nav or redirect edits, edits to rules files such as `AGENTS.md`, and a failed run of the docs repository's own format command.
A pull request still unapproved after 7 days closes and its branch is deleted, so unreviewed pull requests do not pile up in the docs repository.
Each closed pull request captures one `knowledge_writer outcome` event, since auto-merge needs a measured approve rate and time to approval.

Publish checks the `writer-change.json` the run uploads before any branch exists. It refuses what a reviewer cannot be relied on to catch or what would run when the site builds: paths outside the docs folders other than the companion files `KNOWLEDGE_WRITER_COMPANION_FILES` declares and the existing `RULES_FILE_NAMES` files in the root or a folder above a changed page, non-text files, changed nav or `links` lines that are not plain data, and redirects that leave the site or could take over a live page.
A nav or redirect edit it cannot tie to a page the change adds or removes is still plain data a reviewer can judge, so it opens a draft pull request that lists the edit instead of throwing the run away.
The sandbox cannot push, so the server commits exactly what it checked, on the docs integration's token, to a branch it creates from the base the run started on.
The checks are a second layer under the review, not a replacement for it.

## Rollout

Every gate below fails closed without an error, so a missing one looks like a quiet day of merges rather than a failure.
Check each one before reading silence as "no docs needed".

Production needs, before any stage:

- The settings in the first bullet above, for the writer team.
- A GitHub integration on the writer team for each repository owner it touches: `PostHog`, to read merges, and the owner of `KNOWLEDGE_WRITER_DOCS_REPOSITORY`, to publish. [backend/README.md](backend/README.md) covers how one is picked.
- `GITHUB_APP_SLUG`, without which no open docs pull request counts as the writer's, so the open pull request cap stops working.
- `AI_GATEWAY_URL` and `AI_GATEWAY_API_KEY`, which the merge check's judge needs.
- The `knowledge_writer_merged_pull_requests` webhook consumer and the `knowledge-writer-merge-reconcile-schedule` Temporal schedule, which start the merge checks.

Stages, in order:

1. Shadow. Turn on [`knowledge-writer`](https://us.posthog.com/project/2/feature-flags/1036127), the kill switch, and keep [`knowledge-writer-agent-launch`](https://us.posthog.com/project/2/feature-flags/1036128) off. Every `master` merge gets a `knowledge_writer verdict` event, and intake returns `shadow` for each `needs_docs` one instead of starting a run. Before stage 2, check that verdicts arrive for each merge, that `reason: merge_check_failed` is rare, and that `needs_docs` verdicts name the right pages.
2. Launch. Turn on `knowledge-writer-agent-launch` and keep `knowledge-writer-open-prs` off. A `needs_docs` verdict starts a writer run whose finished draft is captured as a `knowledge_writer draft` event (outcome `logged`) with no pull request. No branch is created, and the event's `files` carry each changed file's patch. Read those drafts before stage 3.
3. Open pull requests. Turn on `knowledge-writer-open-prs`. A finished run opens a draft pull request on `KNOWLEDGE_WRITER_DOCS_REPOSITORY`, held to `DAILY_RUN_CAP` and `OPEN_PULL_REQUEST_CAP` in `backend/logic/caps.py`. Check that finished runs upload a `writer-change.json` artifact and get a draft pull request, that no task carries a `knowledge_writer_pull_request_failure` state entry, and which `WriterCapReached` alerts error tracking shows.

To back out, turn off `knowledge-writer-open-prs` to stop opening pull requests, or `knowledge-writer-agent-launch` to stop new runs, which still lets runs already going publish.
Turn off `knowledge-writer` to stop everything, publishing included.
