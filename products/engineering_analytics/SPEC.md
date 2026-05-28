# engineering_analytics — Engineering Spec

Owner: team-devex
Sibling doc: [README.md](./README.md) — read that first for the product picture, motivations, and the wedge. This file is the engineering contract: architecture, canonical types, file layout, ordering.

## 1. Purpose

Engineering contract for the `products/engineering_analytics/` product. The product surfaces PR + CI lifecycle data from the warehouse (`github_pull_requests`, `github_workflow_runs`) as MCP tools and DRF endpoints. Consumers and motivations are in the README.

## 2. Non-goals

- Per-developer surveillance metrics or rankings. Filters operate at cohort level by default.
- Real-time alerting on individual PRs. That's notification surface, not analytics.
- Replacing GitHub's own UI. We surface signal, not the raw PR thread.
- Code-quality static analysis. Different product space.

## 3. Architecture

```mermaid
graph TB
    subgraph Consumers
        MCP[MCP clients - Claude Code / Cursor / PostHog AI]
        UI[Read-only demo UI - React + kea]
        Other[PostHog Code and other agent-driven callers]
    end

    subgraph "Surface (autogen)"
        Tools["MCP tools<br/>(tools.yaml -> codegen)"]
        DRF["DRF viewsets<br/>(@extend_schema)"]
    end

    subgraph Domain
        Facade["facade/api.py<br/>(public interface, canonical types)"]
        Logic["logic/<br/>(metric definitions)"]
        Queries["logic/queries/<br/>(HogQL queries, GitHub-shaped)"]
    end

    subgraph Storage
        WH[(warehouse<br/>github_pull_requests<br/>github_workflow_runs)]
    end

    MCP --> Tools
    UI --> DRF
    Other --> Tools
    Tools --> DRF
    DRF --> Facade
    Facade --> Logic
    Logic --> Queries
    Queries --> WH
```

Rules:

- HogQL via `execute_hogql_query()` is the only data access pattern. No raw ClickHouse `sync_execute()`.
- Django ORM is not used by this product. There is no product Postgres DB in v1 — see README → Locked decisions.
- `logic/queries/` is the only module that names warehouse tables (`github_pull_requests`, `github_workflow_runs`). Logic and facade work with canonical types only.
- One contract feeds both surfaces: DRF viewsets with `@extend_schema` produce OpenAPI → TypeScript types AND MCP tool descriptions. Logic functions are called by both.
- Every MCP-tools PR ships with a matching in-product skill at `skills/<name>/SKILL.md` so the dogfooder has an installed playbook for chaining tool calls — same pattern as `products/visual_review/skills/triaging-visual-review-runs/`.
- Provider abstraction (`CodeHostProvider` Protocol) is **deferred**. GitHub-specific HogQL lives in `logic/queries/` directly; when a second provider lands, the Protocol is extracted then. See §7.

## 4. Canonical types

Defined in `backend/facade/contracts.py` as `pydantic.dataclasses.dataclass(frozen=True)` — same `is_dataclass()` semantics as the stdlib variant (so `DataclassSerializer` works) but with runtime validation at construction. No Django imports.

```mermaid
classDiagram
    class RepoRef {
        +str provider
        +str owner
        +str name
    }
    class Author {
        +str handle
        +str display_name
        +str avatar_url
        +bool is_bot
    }
    class PRState {
        <<enum>>
        OPEN
        CLOSED
        MERGED
    }
    class WorkflowConclusion {
        <<enum>>
        SUCCESS
        FAILURE
        CANCELLED
        SKIPPED
        TIMED_OUT
        NEUTRAL
    }
    class PullRequest {
        +int id
        +int number
        +str title
        +Author author
        +RepoRef repo
        +PRState state
        +bool is_draft
        +datetime created_at
        +datetime merged_at
        +datetime closed_at
    }
    class WorkflowRun {
        +int id
        +str workflow_name
        +str head_sha
        +WorkflowConclusion conclusion
        +datetime run_started_at
        +datetime updated_at
        +int duration_seconds
    }
    PullRequest --> Author
    PullRequest --> RepoRef
    PullRequest --> PRState
    WorkflowRun --> WorkflowConclusion
```

`is_bot` on `Author` is set inside the query / mapping layer:
`is_bot = handle.endswith("[bot]") OR handle in KNOWN_BOT_HANDLES`.

Tool-specific return types (`WorkflowReport`, `TimeToMerge`, `PRLifecycle`) live in `facade/contracts.py` alongside the canonical types. They wrap rows + a `metric_quality` field per README → Locked decisions.

Types named in the README but not in v1 contracts (reviewers, deploys, file paths) wait until the corresponding warehouse data lands.

## 5. v1 tool catalog

Tools live in `products/engineering_analytics/mcp/tools.yaml`. Each tool description is prompt-engineered — it explains to the calling LLM **when** and **why** to call it, not just the parameter list. Tool return shapes are typed contracts, not free-form prose (README → Locked decisions).

| Tool              | Source data            | Returns                                                                                                    | Quality                                                |
| ----------------- | ---------------------- | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| `workflow_report` | `github_workflow_runs` | `list[WorkflowReportRow]` — workflow name, total runs, success rate, median + p95 duration, last failed at | precise                                                |
| `time_to_merge`   | `github_pull_requests` | `list[TimeToMergeRow]` — `bucket` (overall or per author), pr_count, median + p95 seconds                  | coarse (combines draft + ready-for-review time)        |
| `pr_lifecycle`    | both                   | `PRLifecycle` — PR header + timeline of CI run events                                                      | partial (no reviews/comments until reviews data lands) |

All tools accept `date_from` / `date_to` per PostHog convention (relative `-7d` or ISO8601). Optional `repo` filter on the first two.

UI: one read-only scene rendering `workflow_report` as a horizontal bar chart of slowest workflows. Design system showcase only. No filters, no kea forms, no saved views.

## 6. PR ordering

Vertical slices. Each PR independently mergeable. Draft-only by default. No date commitments.

| Step | PR                                                                                                                                                                               | Output                                      | Status            |
| ---- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- | ----------------- |
| 1    | #58888 — scaffold + SPEC.md + README.md                                                                                                                                          | Empty product shell, this doc, product doc  | In progress       |
| 2    | #58890 — `github_workflow_runs` warehouse source                                                                                                                                 | CI run data ingested                        | Ready for review  |
| 3    | New — `workflow_report` + `time_to_merge` + `pr_lifecycle` MCP tools (HogQL → logic → facade → DRF → MCP, one vertical slice with all three) + matching `skills/<name>/SKILL.md` | First useful MCP tools + installed playbook | Pending step 2    |
| 4    | New — read-only UI scene for `workflow_report`                                                                                                                                   | Demo surface                                | Pending step 3    |
| 5    | New (parallel) — `pull_request_reviews` warehouse source                                                                                                                         | Unblocks the wedge tool when we build it    | Independent track |

Rule: each PR independently mergeable. Bottom must be merged before the next opens for review. Draft-only until manual approval.

## 7. Locked decisions

Engineering-specific decisions. Product-level decisions live in README → Locked decisions. If you want to change one, do it in a separate PR with a written reason.

- **HogQL only for analytics data.** No raw ClickHouse.
- **No product Postgres DB.** Saved state lives in the agent's memory; tool calls are stateless. No `db_routing.yaml` entry — analytics data is in the warehouse / ClickHouse (shared infra, nothing to provision). If a product-config model is ever needed, it goes on the **main** DB as a team-scoped model (`TeamScopedRootMixin`), not a separate DB.
- **Provider abstraction deferred.** No `CodeHostProvider` Protocol in v1. GitHub-shaped HogQL lives in `logic/queries/`. The boundary between `logic/queries/` and `logic/` is the future Protocol seam — keep canonical types above it, GitHub-isms below.
- **Canonical types live in `facade/contracts.py`** as frozen dataclasses. No Django imports, no provider-specific fields.
- **CI granularity = workflow level** (`github_workflow_runs`). Job-level breakdown requires a new warehouse endpoint and is deferred.
- **Bot detection** lives in the query / mapping layer: `handle.endswith("[bot]") OR handle in KNOWN_BOT_HANDLES`. Hardcoded allowlist for v1; per-team config deferred.
- **Bots and drafts excluded by default** in PR-listing / cycle-time tools. They are first-class in any future bot-impact analysis (don't strip them everywhere).
- **`time_to_merge` v1** = `merged_at - created_at`. Marked `metric_quality = "coarse"`. Precise companion lands when state-transition data exists.
- **Tool return shapes** = typed pydantic / dataclasses with explicit `metric_quality` marker (`"precise" | "coarse" | "partial"`). Repo convention.
- **Each PR independently mergeable. Draft-only by default.** No bundled stacks.

## 8. Deferred (engineering) decisions

Use the current default; revisit when the relevant PR lands.

- Team taxonomy (CODEOWNERS vs config file vs author allowlist) — defer until team-level rollups are asked for.
- Cycle time variants (first-commit, ready-for-review, first-approval) — wait for reviews + state-transition data.
- Deploy definition (Deployments API vs named workflow vs tag push) — defer until deploys ingestion lands.
- Path-based filtering (which files a PR touched) — deferred; warehouse list endpoint doesn't return file lists. Needs per-PR `/files` fan-out.
- Commits-till-merged — same per-PR detail fan-out cost as paths. Deferred.
- Provider Protocol — wait for second provider. The query layer boundary is already drawn to make extraction mechanical.

## 9. Data sources

Available in v1:

- `github_pull_requests` — PR list endpoint data. Has number, title, author, state, created_at, merged_at, closed_at, draft flag, base/head refs.
- `github_workflow_runs` — landing in #58890. Has workflow name, status, conclusion, run_started_at, updated_at, head SHA.

Deferred (each is a separate warehouse-source PR):

- `pull_request_reviews` — needed for review-event tools and the wedge POC. Per-PR fan-out (~49k calls to backfill busy repos).
- `pull_request_files` — needed for path-based filtering and grouping. Same fan-out shape.
- `pull_request_commits` — needed for commits-till-merged. Same fan-out shape.
- `deployments` / workflow-based deploy detection — needed for DORA + the wedge.

These follow the `implementing-warehouse-sources` skill.

## 10. Lessons from prior closed stacks

Third attempt at a related product. Two prior stacks abandoned without merging anything:

- **#51818 / #51820 / #51824** (closed 2026-04-21). Empty test files, scope creep, abandoned.
- **#55316 → #55322** (closed 2026-04-27). 7-PR Graphite rope. Bottom PR had ~80 failing Django jobs because v0 declared six models in one initial migration with a separate-DB app without full plumbing. No reviewer ever engaged. Whole stack died together. The empty `products/ci_monitoring/` husk on master is what's left.

Antibodies encoded:

1. **Each PR mergeable independently.** PR 1 must be on master before PR 2 opens for review.
2. **PR 1 ships zero business logic.** Just structure, stubs, and this doc + the brief. Nothing to be "wrong" about.
3. **Vertical slices, not horizontal layers.** Each feature PR delivers a complete read path (HogQL → logic → facade → DRF → MCP).
4. **Draft-only by default.** Reviewer attention is the rate limit.
5. **Salvageable nuggets > rope.** If a stack stalls, single PRs land standalone.

## 11. Reference reading

- [README.md](./README.md) — product picture, motivations, locked decisions, glossary (read this first)
- `products/architecture.md` — folder structure, isolation rules, tach + import-linter
- `products/README.md` — how to scaffold a product
- `posthog/models/scoping/README.md` — `TeamScopedRootMixin` contract (main-DB team-scoped model, for whenever the first config model lands)
- Closed-stack PRs #55316–#55322 — what not to do
