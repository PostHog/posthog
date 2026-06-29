# Stampede — monorepo merge queue

Stampede is a merge queue for a single repository. Instead of merging an approved PR straight
to the default branch, it enrolls the PR, runs the **full CI suite against the state the PR
would land on** (a _trial_), and merges only once that trial is green. This keeps the default
branch always-green even when many PRs land close together.

The engine is the public surface in [`backend/facade/`](backend/facade/); everything else
(lifecycle, projected state, GitHub adapter, Temporal workflow) sits behind it.

## How it works

- **Enrollment** — an approved, green PR is admitted to a **partition** and given a **slot**
  (its position in line).
- **Trial** — the engine opens a trial: the full test suite run against the PR's _projected
  state_ (what the repo looks like once the things ahead of it merge). No test selection — the
  full suite, always.
- **Merge / eject** — a green trial makes the slot mergeable; once every slot for the PR is
  green it merges. A real (non-flaky) failure ejects the PR, which can re-enroll at the back of
  the line.
- **Every state change emits a `QueueEvent`** — the append-only audit/observability log.

### Partitions

A **partition** is an independent lane of the queue with its own admission predicate, strategy,
and CI scope. Partition config is authored in a `partitions.yml` and synced into the
`Partition` table on deploy; only runtime fields (`mode`, freeze state) are mutated live via the
facade.

- **Strategy** — `optimistic` (trial against the branch HEAD; lanes run concurrently) or
  `serial` (trial against HEAD + the single predecessor; one at a time). `speculative`,
  `batched`, and `auto` exist in the schema but are not implemented yet.
- **Mode** — `hybrid` (queue runs alongside direct merges) or `exclusive` (every merge goes
  through the queue).

### Eligibility predicate

Admission is gated by a small condition grammar (see
[`backend/grammar/parser.py`](backend/grammar/parser.py)). Whitespace-separated atoms, implicit
AND, optional `!`/`not` negation:

```text
approved            # at least one approving review, not from the PR author
checks-green        # all required checks green
files~=<glob>       # changed files match a glob, e.g. files~=frontend/**
label=<name>        # PR carries a label, e.g. label=merge-queue
```

The default admission predicate is `approved checks-green`.

### Shadow mode

A partition runs in **shadow** until promoted: the engine executes its full logic against real
PRs and **records what it would do without acting** (no real merges, no commit statuses). The
`QueueEvent` log still captures every decision, so you can compare the queue's would-be
outcomes against actual human/direct-merge outcomes before going live. The whole engine is
currently shadow-only.

## Setting it up on a GitHub repo

> Status: the engine, eligibility grammar, lifecycle, and Temporal trial workflow are in place
> and exercised in shadow. The inbound webhook HTTP entrypoint and the live outbound path
> (real merges, commit statuses, default-branch resolution) are not wired yet — so today setup
> means standing up the pieces below and observing shadow decisions.

1. **GitHub App integration.** Stampede reuses the same GitHub App integration model as
   `products/tasks` (`github_integration`). Install the App on the target repo with permissions
   to read PRs/checks and (once live) merge PRs and post commit statuses, then create the
   `Integration` row. Wire the engine's external seams to it via
   `github.adapter.install_engine_bindings(integration_id=...)`.

2. **Bot accounts (if agents open PRs).** Register each automated author's GitHub login in the
   `BotRegistry` ([`backend/github/bot_accounts.py`](backend/github/bot_accounts.py)). This
   attributes queue actions correctly and enforces the **self-approval guard**: a bot's approval
   of its own PR never satisfies `approved`. Human PRs need no registration.

3. **Define partitions.** Author the repo's lanes in `partitions.yml` — name, admission
   `predicate`, `strategy`, `ci_scope` (the affected-target selector for the lane), and
   `precedence` (tiebreak for routing). Sync them into the `Partition` table. Start with a
   single partition matching everything; split later.

4. **Run the Temporal worker.** Trials are durable Temporal workflows on the
   `merge-queue-task-queue` (`settings.MERGE_QUEUE_TASK_QUEUE`). Make sure a worker registers
   the merge-queue workflow + activities (already registered in
   `start_temporal_worker`). In local dev all queues collapse onto the single
   `development-task-queue`.

5. **Feed PR signals in.** As PR webhooks arrive (review submitted, check-suite completed,
   push, label), assemble a `PullRequestSignal` and call `github.adapter.ingest(signal)`. The
   adapter normalizes it to `PRFacts`, evaluates the partition predicate, and enrolls eligible
   PRs. Ingest is idempotent — re-delivering a webhook for an enrolled PR just returns its
   status.

6. **Watch, then promote.** Leave the partition in shadow and review the `QueueEvent` timeline
   (and, later, the `engineering_analytics` stream) against real outcomes. Promote a partition
   out of shadow per-partition once its shadow decisions match reality.

### Operating the queue

All mutations go through the facade ([`backend/facade/api.py`](backend/facade/api.py)):

- `enroll` / `dequeue` / `status` — manage and inspect a PR's place in line.
- `freeze` / `unfreeze` — pause a partition (or the whole queue). In-flight trials still
  finish, but nothing new starts and nothing merges until unfreeze.
- `break_glass` — **human-only** forced merge / bypass (agents and the orchestrator can never
  call it; this is the one hard authorization gate).

## PostHog/posthog setup

For the PostHog monorepo specifically:

- **Repo & App.** Target is `PostHog/posthog`. Reuse the existing PostHog GitHub App
  integration (`github_integration`, same as `products/tasks`) rather than registering a new
  App — create/point an `Integration` row at the `PostHog/posthog` installation.
- **Tables are instance-global.** Stampede's models key on `repo` ("owner/name"), not on a
  customer Team — they are infra tables for PostHog's own monorepo, so they are exempt from
  team scoping by design.
- **Required checks.** `checks-green` is conservative: it requires a non-empty set of required
  checks, all green. Make sure the PR's required check set includes the Visual Review gate and
  the suites that actually gate master, so a PR with no required checks is never treated as
  green.
- **Agent PRs.** Register PostHog's automation bot logins in the `BotRegistry` so their PRs are
  attributed as `agent` and their self-approvals don't clear `approved`.
- **Partitions.** Start with one `optimistic`, `hybrid` partition admitting
  `approved checks-green` across the repo and observe in shadow. Split into per-area lanes
  (e.g. `files~=frontend/**`, `files~=rust/**`) via `partitions.yml` as the queue proves out.
- **Temporal.** Trials run on `merge-queue-task-queue` in production; locally they run on the
  collapsed `development-task-queue`. Confirm the merge-queue worker is registered before
  enrolling anything that should actually trial.

## Current status

Implemented and tested (in shadow): the data model, facade, condition grammar, lifecycle state
machine (enroll → trial → merge/eject, back-of-line re-enroll, freeze), optimistic + serial
projected state, the GitHub adapter's ingest/eligibility/enroll path, per-agent bot accounts,
the shadow guard, and the Temporal trial workflow.

Stubbed / not yet wired (tracked as `TODO`s in the code):

- the inbound webhook HTTP entrypoint and the live outbound path (real merges, commit statuses,
  default-branch resolution);
- real CI dispatch for `run_full_suite` (currently an injectable seam — tests supply a runner);
- the `engineering_analytics` emission;
- the flaky-test signal (currently treats nothing as flaky, so every real failure ejects);
- Cowboy, the AI orchestrator above the engine (the engine runs fully deterministically with it
  absent).

## Local testing

The queue has no UI/HTTP surface yet — drive the engine through the facade in a Django shell or
script.
