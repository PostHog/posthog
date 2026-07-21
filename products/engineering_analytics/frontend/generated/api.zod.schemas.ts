/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const CICardSummaryApi = zod.object({
    open_prs: zod.number().describe('Count of open pull requests.'),
    repos: zod.number().describe('Distinct repositories with at least one open pull request.'),
    stuck: zod.number().describe('Open, non-draft, non-bot pull requests older than 7 days.'),
    failing_ci: zod
        .number()
        .describe(
            'Open pull requests with at least one failing latest CI run. May lag until the workflow_run webhook settles late completions.'
        ),
})

export type CICardSummaryApi = zod.input<typeof CICardSummaryApi>
export type CICardSummaryApiOutput = zod.output<typeof CICardSummaryApi>

export const WorkflowCostApi = zod.object({
    workflow_name: zod.string().describe('GitHub Actions workflow name this cost is for.'),
    billable_minutes: zod.number().describe('Billable (self-hosted) minutes for this workflow within the scope.'),
    estimated_cost_usd: zod
        .number()
        .nullable()
        .describe('Estimated dollar cost for this workflow, or null when nothing was costable.'),
    costed_jobs: zod.number().describe('Costed jobs for this workflow (billable Linux runner, finished).'),
    unsettled_jobs: zod.number().describe('Billable Linux jobs still queued\/running for this workflow.'),
    excluded_jobs: zod.number().describe('Provider-hosted\/non-Linux jobs for this workflow, outside the estimate.'),
})

export type WorkflowCostApi = zod.input<typeof WorkflowCostApi>
export type WorkflowCostApiOutput = zod.output<typeof WorkflowCostApi>

export const RunCostApi = zod.object({
    run_id: zod.number().describe('GitHub Actions run id this cost is for.'),
    run_attempt: zod.number().describe('Re-run attempt number; 1 for the first attempt.'),
    billable_minutes: zod.number().describe('Billable (self-hosted) minutes for this run attempt.'),
    estimated_cost_usd: zod
        .number()
        .nullable()
        .describe('Estimated dollar cost for this run attempt, or null when nothing was costable.'),
})

export type RunCostApi = zod.input<typeof RunCostApi>
export type RunCostApiOutput = zod.output<typeof RunCostApi>

export const PRCostSummaryApi = zod.object({
    by_workflow: zod
        .array(
            zod.object({
                workflow_name: zod.string().describe('GitHub Actions workflow name this cost is for.'),
                billable_minutes: zod
                    .number()
                    .describe('Billable (self-hosted) minutes for this workflow within the scope.'),
                estimated_cost_usd: zod
                    .number()
                    .nullable()
                    .describe('Estimated dollar cost for this workflow, or null when nothing was costable.'),
                costed_jobs: zod.number().describe('Costed jobs for this workflow (billable Linux runner, finished).'),
                unsettled_jobs: zod.number().describe('Billable Linux jobs still queued\/running for this workflow.'),
                excluded_jobs: zod
                    .number()
                    .describe('Provider-hosted\/non-Linux jobs for this workflow, outside the estimate.'),
            })
        )
        .describe('Same spend broken down per workflow.'),
    by_run: zod
        .array(
            zod.object({
                run_id: zod.number().describe('GitHub Actions run id this cost is for.'),
                run_attempt: zod.number().describe('Re-run attempt number; 1 for the first attempt.'),
                billable_minutes: zod.number().describe('Billable (self-hosted) minutes for this run attempt.'),
                estimated_cost_usd: zod
                    .number()
                    .nullable()
                    .describe('Estimated dollar cost for this run attempt, or null when nothing was costable.'),
            })
        )
        .describe('Same spend broken down per workflow run, keyed by (run_id, run_attempt).'),
    jobs_available: zod
        .boolean()
        .describe(
            "False when the job-level source (github_workflow_jobs) isn't synced — every figure is then zero\/null and the cost cards should be hidden."
        ),
    billable_minutes: zod
        .number()
        .describe(
            "Billable CI minutes: each costed (self-hosted) job's elapsed time, summed. Parallel jobs add up, so this is compute time spent, not wall-clock run duration."
        ),
    estimated_cost_usd: zod
        .number()
        .nullable()
        .describe(
            'Estimated dollar cost (sum of per-job estimates: elapsed x tier multiplier x reference rate). Null when no job was costable.'
        ),
    costed_jobs: zod.number().describe('Jobs counted in the estimate (billable Linux runner, finished).'),
    unsettled_jobs: zod
        .number()
        .describe('Billable Linux jobs still queued\/running (no elapsed) — excluded from the estimate.'),
    excluded_jobs: zod
        .number()
        .describe('Jobs on provider-hosted (GitHub-hosted, free) or non-Linux runners — outside the estimate.'),
})

export type PRCostSummaryApi = zod.input<typeof PRCostSummaryApi>
export type PRCostSummaryApiOutput = zod.output<typeof PRCostSummaryApi>

export const AuthorApi = zod.object({
    handle: zod.string().describe('Login handle of the pull request author.'),
    display_name: zod.string().describe('Human-readable name; equals the handle in v1.'),
    avatar_url: zod.string().describe("URL of the author's avatar image."),
    is_bot: zod.boolean().describe('True if the author is a bot (handle ends in [bot] or is a known bot).'),
})

export type AuthorApi = zod.input<typeof AuthorApi>
export type AuthorApiOutput = zod.output<typeof AuthorApi>

export const RepoRefApi = zod.object({
    provider: zod.string().describe("Code host provider, e.g. 'github'."),
    owner: zod.string().describe('Repository owner or organization.'),
    name: zod.string().describe('Repository name.'),
})

export type RepoRefApi = zod.input<typeof RepoRefApi>
export type RepoRefApiOutput = zod.output<typeof RepoRefApi>

export const EngineeringAnalyticsPRStateEnumApi = zod
    .enum(['open', 'closed', 'merged'])
    .describe('\* `open` - OPEN\n\* `closed` - CLOSED\n\* `merged` - MERGED')

export type EngineeringAnalyticsPRStateEnumApi = zod.input<typeof EngineeringAnalyticsPRStateEnumApi>
export type EngineeringAnalyticsPRStateEnumApiOutput = zod.output<typeof EngineeringAnalyticsPRStateEnumApi>

export const PullRequestApi = zod.object({
    author: zod
        .object({
            handle: zod.string().describe('Login handle of the pull request author.'),
            display_name: zod.string().describe('Human-readable name; equals the handle in v1.'),
            avatar_url: zod.string().describe("URL of the author's avatar image."),
            is_bot: zod.boolean().describe('True if the author is a bot (handle ends in [bot] or is a known bot).'),
        })
        .describe('The pull request author.'),
    repo: zod
        .object({
            provider: zod.string().describe("Code host provider, e.g. 'github'."),
            owner: zod.string().describe('Repository owner or organization.'),
            name: zod.string().describe('Repository name.'),
        })
        .describe('Repository the pull request belongs to.'),
    id: zod.number().describe('GitHub pull request id.'),
    number: zod.number().describe('Pull request number within the repository.'),
    title: zod.string().describe('Pull request title.'),
    state: zod
        .enum(['open', 'closed', 'merged'])
        .describe('\* `open` - OPEN\n\* `closed` - CLOSED\n\* `merged` - MERGED')
        .describe(
            "Derived state: 'open', 'closed', or 'merged'.\n\n\* `open` - OPEN\n\* `closed` - CLOSED\n\* `merged` - MERGED"
        ),
    is_draft: zod.boolean().describe('True if the pull request is a draft.'),
    created_at: zod.iso.datetime({ offset: true }).describe('When the pull request was opened.'),
    merged_at: zod.iso.datetime({ offset: true }).nullable().describe('When the pull request was merged, or null.'),
    closed_at: zod.iso.datetime({ offset: true }).nullable().describe('When the pull request was closed, or null.'),
})

export type PullRequestApi = zod.input<typeof PullRequestApi>
export type PullRequestApiOutput = zod.output<typeof PullRequestApi>

export const PRLifecycleEventKindEnumApi = zod
    .enum(['opened', 'ci_started', 'ci_finished', 'merged', 'closed'])
    .describe(
        '\* `opened` - OPENED\n\* `ci_started` - CI_STARTED\n\* `ci_finished` - CI_FINISHED\n\* `merged` - MERGED\n\* `closed` - CLOSED'
    )

export type PRLifecycleEventKindEnumApi = zod.input<typeof PRLifecycleEventKindEnumApi>
export type PRLifecycleEventKindEnumApiOutput = zod.output<typeof PRLifecycleEventKindEnumApi>

export const PRLifecycleEventApi = zod.object({
    kind: zod
        .enum(['opened', 'ci_started', 'ci_finished', 'merged', 'closed'])
        .describe(
            '\* `opened` - OPENED\n\* `ci_started` - CI_STARTED\n\* `ci_finished` - CI_FINISHED\n\* `merged` - MERGED\n\* `closed` - CLOSED'
        )
        .describe(
            'Event kind: opened, ci_started, ci_finished, merged, or closed.\n\n\* `opened` - OPENED\n\* `ci_started` - CI_STARTED\n\* `ci_finished` - CI_FINISHED\n\* `merged` - MERGED\n\* `closed` - CLOSED'
        ),
    at: zod.iso.datetime({ offset: true }).describe('When the event occurred.'),
    detail: zod.string().nullish().describe('Optional detail, e.g. workflow name and conclusion for CI events.'),
    run_id: zod
        .number()
        .nullish()
        .describe('GitHub Actions run id for ci_started\/ci_finished events, null otherwise.'),
})

export type PRLifecycleEventApi = zod.input<typeof PRLifecycleEventApi>
export type PRLifecycleEventApiOutput = zod.output<typeof PRLifecycleEventApi>

export const MetricQualityEnumApi = zod
    .enum(['precise', 'coarse', 'partial'])
    .describe('\* `precise` - PRECISE\n\* `coarse` - COARSE\n\* `partial` - PARTIAL')

export type MetricQualityEnumApi = zod.input<typeof MetricQualityEnumApi>
export type MetricQualityEnumApiOutput = zod.output<typeof MetricQualityEnumApi>

export const PRLifecycleApi = zod.object({
    pull_request: zod
        .object({
            author: zod
                .object({
                    handle: zod.string().describe('Login handle of the pull request author.'),
                    display_name: zod.string().describe('Human-readable name; equals the handle in v1.'),
                    avatar_url: zod.string().describe("URL of the author's avatar image."),
                    is_bot: zod
                        .boolean()
                        .describe('True if the author is a bot (handle ends in [bot] or is a known bot).'),
                })
                .describe('The pull request author.'),
            repo: zod
                .object({
                    provider: zod.string().describe("Code host provider, e.g. 'github'."),
                    owner: zod.string().describe('Repository owner or organization.'),
                    name: zod.string().describe('Repository name.'),
                })
                .describe('Repository the pull request belongs to.'),
            id: zod.number().describe('GitHub pull request id.'),
            number: zod.number().describe('Pull request number within the repository.'),
            title: zod.string().describe('Pull request title.'),
            state: zod
                .enum(['open', 'closed', 'merged'])
                .describe('\* `open` - OPEN\n\* `closed` - CLOSED\n\* `merged` - MERGED')
                .describe(
                    "Derived state: 'open', 'closed', or 'merged'.\n\n\* `open` - OPEN\n\* `closed` - CLOSED\n\* `merged` - MERGED"
                ),
            is_draft: zod.boolean().describe('True if the pull request is a draft.'),
            created_at: zod.iso.datetime({ offset: true }).describe('When the pull request was opened.'),
            merged_at: zod.iso
                .datetime({ offset: true })
                .nullable()
                .describe('When the pull request was merged, or null.'),
            closed_at: zod.iso
                .datetime({ offset: true })
                .nullable()
                .describe('When the pull request was closed, or null.'),
        })
        .describe('The pull request header.'),
    events: zod
        .array(
            zod.object({
                kind: zod
                    .enum(['opened', 'ci_started', 'ci_finished', 'merged', 'closed'])
                    .describe(
                        '\* `opened` - OPENED\n\* `ci_started` - CI_STARTED\n\* `ci_finished` - CI_FINISHED\n\* `merged` - MERGED\n\* `closed` - CLOSED'
                    )
                    .describe(
                        'Event kind: opened, ci_started, ci_finished, merged, or closed.\n\n\* `opened` - OPENED\n\* `ci_started` - CI_STARTED\n\* `ci_finished` - CI_FINISHED\n\* `merged` - MERGED\n\* `closed` - CLOSED'
                    ),
                at: zod.iso.datetime({ offset: true }).describe('When the event occurred.'),
                detail: zod
                    .string()
                    .nullish()
                    .describe('Optional detail, e.g. workflow name and conclusion for CI events.'),
                run_id: zod
                    .number()
                    .nullish()
                    .describe('GitHub Actions run id for ci_started\/ci_finished events, null otherwise.'),
            })
        )
        .describe('Lifecycle events ordered by time.'),
    metric_quality: zod
        .enum(['precise', 'coarse', 'partial'])
        .describe('\* `precise` - PRECISE\n\* `coarse` - COARSE\n\* `partial` - PARTIAL')
        .optional()
        .describe(
            "Always 'partial' — CI events only; reviews and comments are not yet available.\n\n\* `precise` - PRECISE\n\* `coarse` - COARSE\n\* `partial` - PARTIAL"
        ),
})

export type PRLifecycleApi = zod.input<typeof PRLifecycleApi>
export type PRLifecycleApiOutput = zod.output<typeof PRLifecycleApi>

export const WorkflowRunActivityApi = zod.object({
    points: zod
        .array(
            zod.object({
                run_id: zod.number().describe('GitHub Actions run id.'),
                conclusion: zod
                    .string()
                    .nullable()
                    .describe(
                        "Run conclusion ('success', 'failure', 'timed_out', 'cancelled', 'skipped', ...), or null while still in progress."
                    ),
                run_started_at: zod.iso
                    .datetime({ offset: true })
                    .nullable()
                    .describe('When the run started, or null for a queued\/barely-started run.'),
                duration_seconds: zod
                    .number()
                    .nullable()
                    .describe('Wall-clock duration in seconds; null until the run completes.'),
                head_branch: zod.string().describe("Git branch the run was triggered on, or '' when unknown."),
                pr_number: zod.number().describe('Attributed pull request number, or 0 when unattributed.'),
            })
        )
        .describe('Per-run chart points, newest first, capped at `limit`.'),
    truncated: zod
        .boolean()
        .describe(
            'True when more runs matched than the cap; `points` is the newest `limit` runs, so the chart covers only the most recent activity, not the full window.'
        ),
    limit: zod.number().describe('Maximum number of run points returned in `points`.'),
})

export type WorkflowRunActivityApi = zod.input<typeof WorkflowRunActivityApi>
export type WorkflowRunActivityApiOutput = zod.output<typeof WorkflowRunActivityApi>

export const WorkflowRunDetailApi = zod.object({
    repo: zod
        .object({
            provider: zod.string().describe("Code host provider, e.g. 'github'."),
            owner: zod.string().describe('Repository owner or organization.'),
            name: zod.string().describe('Repository name.'),
        })
        .describe('Repository the run belongs to.'),
    id: zod.number().describe('GitHub Actions run id.'),
    workflow_name: zod.string().describe('GitHub Actions workflow name.'),
    head_sha: zod.string().describe('Commit SHA the run was triggered on.'),
    head_branch: zod.string().describe('Git branch the run was triggered on.'),
    status: zod.string().describe("Raw run status: 'queued', 'in_progress', 'completed', etc."),
    conclusion: zod
        .string()
        .nullable()
        .describe(
            "Run conclusion ('success', 'failure', 'timed_out', 'cancelled', 'skipped', 'action_required', ...), or null while still in progress."
        ),
    run_started_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the run started, or null for a queued\/barely-started run.'),
    updated_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the run was last updated (its finish time once completed), or null when unstarted.'),
    duration_seconds: zod.number().nullable().describe('Wall-clock duration in seconds; null until the run completes.'),
    run_attempt: zod.number().describe('Re-run attempt number; 1 for the first attempt.'),
    pr_number: zod.number().describe('Attributed pull request number, or 0 when unattributed.'),
})

export type WorkflowRunDetailApi = zod.input<typeof WorkflowRunDetailApi>
export type WorkflowRunDetailApiOutput = zod.output<typeof WorkflowRunDetailApi>

export const CIStatusRollupApi = zod.object({
    runs: zod.number().describe("Distinct workflows run on the PR's head SHA."),
    passing: zod.number().describe("Latest runs that completed with conclusion 'success'."),
    failing: zod.number().describe("Latest runs that completed with conclusion 'failure' or 'timed_out'."),
    pending: zod.number().describe('Latest runs not yet completed (queued or in progress).'),
})

export type CIStatusRollupApi = zod.input<typeof CIStatusRollupApi>
export type CIStatusRollupApiOutput = zod.output<typeof CIStatusRollupApi>

export const PullRequestListItemApi = zod.object({
    author: zod
        .object({
            handle: zod.string().describe('Login handle of the pull request author.'),
            display_name: zod.string().describe('Human-readable name; equals the handle in v1.'),
            avatar_url: zod.string().describe("URL of the author's avatar image."),
            is_bot: zod.boolean().describe('True if the author is a bot (handle ends in [bot] or is a known bot).'),
        })
        .describe('The pull request author.'),
    repo: zod
        .object({
            provider: zod.string().describe("Code host provider, e.g. 'github'."),
            owner: zod.string().describe('Repository owner or organization.'),
            name: zod.string().describe('Repository name.'),
        })
        .describe('Repository the pull request belongs to.'),
    ci: zod
        .object({
            runs: zod.number().describe("Distinct workflows run on the PR's head SHA."),
            passing: zod.number().describe("Latest runs that completed with conclusion 'success'."),
            failing: zod.number().describe("Latest runs that completed with conclusion 'failure' or 'timed_out'."),
            pending: zod.number().describe('Latest runs not yet completed (queued or in progress).'),
        })
        .describe('CI status from the latest workflow runs on the head SHA.'),
    number: zod.number().describe('Pull request number within the repository.'),
    title: zod.string().describe('Pull request title.'),
    state: zod
        .enum(['open', 'closed', 'merged'])
        .describe('\* `open` - OPEN\n\* `closed` - CLOSED\n\* `merged` - MERGED')
        .describe(
            "Derived state: 'open', 'closed', or 'merged'.\n\n\* `open` - OPEN\n\* `closed` - CLOSED\n\* `merged` - MERGED"
        ),
    is_draft: zod.boolean().describe('True if the pull request is a draft.'),
    created_at: zod.iso.datetime({ offset: true }).describe('When the pull request was opened.'),
    merged_at: zod.iso.datetime({ offset: true }).nullable().describe('When the pull request was merged, or null.'),
    open_to_merge_seconds: zod
        .number()
        .nullable()
        .describe(
            'Coarse open-to-merge time in seconds (merged_at - created_at; fuses draft and ready-for-review time). Null until merged.'
        ),
    labels: zod.array(zod.string()).describe('GitHub label names on the pull request.'),
    pushes: zod
        .number()
        .describe(
            'CI triggers attributed to this PR: distinct head SHAs across its workflow runs. Fork-PR runs are unattributed.'
        ),
    rerun_cycles: zod.number().describe('Workflow runs attributed to this PR that were a 2nd+ attempt (a re-run).'),
    estimated_cost_usd: zod
        .number()
        .nullish()
        .describe(
            "Estimated CI cost in USD summed over this PR's jobs (billable runners only). Null when nothing was costable or the job-level source isn't synced."
        ),
    billable_minutes: zod
        .number()
        .nullish()
        .describe("Billable (self-hosted) minutes summed over this PR's jobs. Null when the job source isn't synced."),
})

export type PullRequestListItemApi = zod.input<typeof PullRequestListItemApi>
export type PullRequestListItemApiOutput = zod.output<typeof PullRequestListItemApi>

export const PullRequestListApi = zod.object({
    items: zod
        .array(
            zod.object({
                author: zod
                    .object({
                        handle: zod.string().describe('Login handle of the pull request author.'),
                        display_name: zod.string().describe('Human-readable name; equals the handle in v1.'),
                        avatar_url: zod.string().describe("URL of the author's avatar image."),
                        is_bot: zod
                            .boolean()
                            .describe('True if the author is a bot (handle ends in [bot] or is a known bot).'),
                    })
                    .describe('The pull request author.'),
                repo: zod
                    .object({
                        provider: zod.string().describe("Code host provider, e.g. 'github'."),
                        owner: zod.string().describe('Repository owner or organization.'),
                        name: zod.string().describe('Repository name.'),
                    })
                    .describe('Repository the pull request belongs to.'),
                ci: zod
                    .object({
                        runs: zod.number().describe("Distinct workflows run on the PR's head SHA."),
                        passing: zod.number().describe("Latest runs that completed with conclusion 'success'."),
                        failing: zod
                            .number()
                            .describe("Latest runs that completed with conclusion 'failure' or 'timed_out'."),
                        pending: zod.number().describe('Latest runs not yet completed (queued or in progress).'),
                    })
                    .describe('CI status from the latest workflow runs on the head SHA.'),
                number: zod.number().describe('Pull request number within the repository.'),
                title: zod.string().describe('Pull request title.'),
                state: zod
                    .enum(['open', 'closed', 'merged'])
                    .describe('\* `open` - OPEN\n\* `closed` - CLOSED\n\* `merged` - MERGED')
                    .describe(
                        "Derived state: 'open', 'closed', or 'merged'.\n\n\* `open` - OPEN\n\* `closed` - CLOSED\n\* `merged` - MERGED"
                    ),
                is_draft: zod.boolean().describe('True if the pull request is a draft.'),
                created_at: zod.iso.datetime({ offset: true }).describe('When the pull request was opened.'),
                merged_at: zod.iso
                    .datetime({ offset: true })
                    .nullable()
                    .describe('When the pull request was merged, or null.'),
                open_to_merge_seconds: zod
                    .number()
                    .nullable()
                    .describe(
                        'Coarse open-to-merge time in seconds (merged_at - created_at; fuses draft and ready-for-review time). Null until merged.'
                    ),
                labels: zod.array(zod.string()).describe('GitHub label names on the pull request.'),
                pushes: zod
                    .number()
                    .describe(
                        'CI triggers attributed to this PR: distinct head SHAs across its workflow runs. Fork-PR runs are unattributed.'
                    ),
                rerun_cycles: zod
                    .number()
                    .describe('Workflow runs attributed to this PR that were a 2nd+ attempt (a re-run).'),
                estimated_cost_usd: zod
                    .number()
                    .nullish()
                    .describe(
                        "Estimated CI cost in USD summed over this PR's jobs (billable runners only). Null when nothing was costable or the job-level source isn't synced."
                    ),
                billable_minutes: zod
                    .number()
                    .nullish()
                    .describe(
                        "Billable (self-hosted) minutes summed over this PR's jobs. Null when the job source isn't synced."
                    ),
            })
        )
        .describe('Pull requests, newest first, capped at `limit`.'),
    truncated: zod
        .boolean()
        .describe(
            'True when more pull requests match than the cap; `items` is the newest `limit` rows and the aggregate counts in ci_cards can exceed it.'
        ),
    limit: zod.number().describe('Maximum number of pull requests returned in `items`.'),
})

export type PullRequestListApi = zod.input<typeof PullRequestListApi>
export type PullRequestListApiOutput = zod.output<typeof PullRequestListApi>

export const QuarantineModeEnumApi = zod.enum(['run', 'skip']).describe('\* `run` - RUN\n\* `skip` - SKIP')

export type QuarantineModeEnumApi = zod.input<typeof QuarantineModeEnumApi>
export type QuarantineModeEnumApiOutput = zod.output<typeof QuarantineModeEnumApi>

export const LifecycleEnumApi = zod
    .enum(['active', 'expiring_soon', 'in_grace', 'overdue'])
    .describe(
        '\* `active` - ACTIVE\n\* `expiring_soon` - EXPIRING_SOON\n\* `in_grace` - IN_GRACE\n\* `overdue` - OVERDUE'
    )

export type LifecycleEnumApi = zod.input<typeof LifecycleEnumApi>
export type LifecycleEnumApiOutput = zod.output<typeof LifecycleEnumApi>

export const SelectorKindEnumApi = zod
    .enum(['product', 'file', 'directory', 'test'])
    .describe('\* `product` - PRODUCT\n\* `file` - FILE\n\* `directory` - DIRECTORY\n\* `test` - TEST')

export type SelectorKindEnumApi = zod.input<typeof SelectorKindEnumApi>
export type SelectorKindEnumApiOutput = zod.output<typeof SelectorKindEnumApi>

export const QuarantineEntryApi = zod.object({
    id: zod
        .string()
        .describe("Test selector: an exact test id, a file, a directory, a class prefix, or 'product:<dashed-name>'."),
    runner: zod.string().describe("Test runner the selector targets, e.g. 'pytest' or 'jest'."),
    reason: zod.string().describe('Why the test was quarantined.'),
    owner: zod.string().describe('GitHub team or user handle responsible for the fix.'),
    issue: zod.string().describe('Tracking issue URL, or empty when none was filed.'),
    added: zod.iso.date().describe('ISO date the entry was added.'),
    expires: zod.iso.date().describe('ISO date the quarantine expires; past it the test blocks CI normally again.'),
    mode: zod
        .enum(['run', 'skip'])
        .describe('\* `run` - RUN\n\* `skip` - SKIP')
        .describe(
            "'run' (the test still executes but cannot fail the suite) or 'skip' (not run at all).\n\n\* `run` - RUN\n\* `skip` - SKIP"
        ),
    lifecycle: zod
        .enum(['active', 'expiring_soon', 'in_grace', 'overdue'])
        .describe(
            '\* `active` - ACTIVE\n\* `expiring_soon` - EXPIRING_SOON\n\* `in_grace` - IN_GRACE\n\* `overdue` - OVERDUE'
        )
        .describe(
            "Expiry classification: 'active' (>7 days left), 'expiring_soon' (0-7 days left), 'in_grace' (expired up to 7 days ago), 'overdue' (expired beyond the grace period).\n\n\* `active` - ACTIVE\n\* `expiring_soon` - EXPIRING_SOON\n\* `in_grace` - IN_GRACE\n\* `overdue` - OVERDUE"
        ),
    days_until_expiry: zod.number().describe('Days until the entry expires; negative once past expiry.'),
    selector_kind: zod
        .enum(['product', 'file', 'directory', 'test'])
        .describe('\* `product` - PRODUCT\n\* `file` - FILE\n\* `directory` - DIRECTORY\n\* `test` - TEST')
        .describe(
            "What the selector covers: 'test' (contains '::'), 'file', 'directory', or 'product'.\n\n\* `product` - PRODUCT\n\* `file` - FILE\n\* `directory` - DIRECTORY\n\* `test` - TEST"
        ),
})

export type QuarantineEntryApi = zod.input<typeof QuarantineEntryApi>
export type QuarantineEntryApiOutput = zod.output<typeof QuarantineEntryApi>

export const QuarantineFileApi = zod.object({
    entries: zod
        .array(
            zod.object({
                id: zod
                    .string()
                    .describe(
                        "Test selector: an exact test id, a file, a directory, a class prefix, or 'product:<dashed-name>'."
                    ),
                runner: zod.string().describe("Test runner the selector targets, e.g. 'pytest' or 'jest'."),
                reason: zod.string().describe('Why the test was quarantined.'),
                owner: zod.string().describe('GitHub team or user handle responsible for the fix.'),
                issue: zod.string().describe('Tracking issue URL, or empty when none was filed.'),
                added: zod.iso.date().describe('ISO date the entry was added.'),
                expires: zod.iso
                    .date()
                    .describe('ISO date the quarantine expires; past it the test blocks CI normally again.'),
                mode: zod
                    .enum(['run', 'skip'])
                    .describe('\* `run` - RUN\n\* `skip` - SKIP')
                    .describe(
                        "'run' (the test still executes but cannot fail the suite) or 'skip' (not run at all).\n\n\* `run` - RUN\n\* `skip` - SKIP"
                    ),
                lifecycle: zod
                    .enum(['active', 'expiring_soon', 'in_grace', 'overdue'])
                    .describe(
                        '\* `active` - ACTIVE\n\* `expiring_soon` - EXPIRING_SOON\n\* `in_grace` - IN_GRACE\n\* `overdue` - OVERDUE'
                    )
                    .describe(
                        "Expiry classification: 'active' (>7 days left), 'expiring_soon' (0-7 days left), 'in_grace' (expired up to 7 days ago), 'overdue' (expired beyond the grace period).\n\n\* `active` - ACTIVE\n\* `expiring_soon` - EXPIRING_SOON\n\* `in_grace` - IN_GRACE\n\* `overdue` - OVERDUE"
                    ),
                days_until_expiry: zod.number().describe('Days until the entry expires; negative once past expiry.'),
                selector_kind: zod
                    .enum(['product', 'file', 'directory', 'test'])
                    .describe('\* `product` - PRODUCT\n\* `file` - FILE\n\* `directory` - DIRECTORY\n\* `test` - TEST')
                    .describe(
                        "What the selector covers: 'test' (contains '::'), 'file', 'directory', or 'product'.\n\n\* `product` - PRODUCT\n\* `file` - FILE\n\* `directory` - DIRECTORY\n\* `test` - TEST"
                    ),
            })
        )
        .describe(
            'Quarantined selectors, most urgent first (overdue, in_grace, expiring_soon, active), then by soonest expiry.'
        ),
    repo: zod
        .union([
            zod.object({
                provider: zod.string().describe("Code host provider, e.g. 'github'."),
                owner: zod.string().describe('Repository owner or organization.'),
                name: zod.string().describe('Repository name.'),
            }),
            zod.null(),
        ])
        .describe(
            "Repository the file was read from. Null in local-dev mode, where the server's own checkout is read."
        ),
    available: zod
        .boolean()
        .describe('False when the repository has no quarantine file (not an error) or it could not be fetched.'),
    parse_errors: zod
        .array(zod.string())
        .describe(
            'Contract violations (malformed JSON, bad entries) or fetch failures. Malformed entries are dropped; well-formed ones are kept.'
        ),
    parse_warnings: zod.array(zod.string()).describe('Forward-compatibility notices, e.g. unknown entry fields.'),
    source_url: zod
        .string()
        .describe('GitHub blob URL of the quarantine file, or empty when read locally or unavailable.'),
    generated_at: zod.iso
        .datetime({ offset: true })
        .describe('When this snapshot was computed (UTC); expiry math uses this clock.'),
})

export type QuarantineFileApi = zod.input<typeof QuarantineFileApi>
export type QuarantineFileApiOutput = zod.output<typeof QuarantineFileApi>

export const GitHubSourceApi = zod.object({
    id: zod.string().describe('Source id — pass as `source_id` to the other endpoints to read this source.'),
    repo: zod.string().describe("Connected repository as 'owner\/name', or '' if unknown."),
    prefix: zod.string().describe("User-chosen warehouse table-name prefix for this source, or '' when none."),
})

export type GitHubSourceApi = zod.input<typeof GitHubSourceApi>
export type GitHubSourceApiOutput = zod.output<typeof GitHubSourceApi>

export const WorkflowHealthBucketApi = zod.object({
    bucket_start: zod.iso
        .datetime({ offset: true })
        .describe("Bucket start, aligned to the item's granularity (top of hour, midnight, or Monday)."),
    run_count: zod.number().describe('Runs started in this bucket.'),
    completed: zod.number().describe('Runs that completed in this bucket.'),
    successes: zod.number().describe("Completed runs with conclusion 'success' in this bucket."),
    failures: zod
        .number()
        .describe(
            "Completed runs that failed in this bucket (conclusion 'failure' or 'timed_out'); excludes skipped, cancelled, and action_required runs."
        ),
})

export type WorkflowHealthBucketApi = zod.input<typeof WorkflowHealthBucketApi>
export type WorkflowHealthBucketApiOutput = zod.output<typeof WorkflowHealthBucketApi>

export const WorkflowHealthItemApi = zod.object({
    repo: zod
        .object({
            provider: zod.string().describe("Code host provider, e.g. 'github'."),
            owner: zod.string().describe('Repository owner or organization.'),
            name: zod.string().describe('Repository name.'),
        })
        .describe('Repository the workflow runs in.'),
    buckets: zod
        .array(
            zod.object({
                bucket_start: zod.iso
                    .datetime({ offset: true })
                    .describe("Bucket start, aligned to the item's granularity (top of hour, midnight, or Monday)."),
                run_count: zod.number().describe('Runs started in this bucket.'),
                completed: zod.number().describe('Runs that completed in this bucket.'),
                successes: zod.number().describe("Completed runs with conclusion 'success' in this bucket."),
                failures: zod
                    .number()
                    .describe(
                        "Completed runs that failed in this bucket (conclusion 'failure' or 'timed_out'); excludes skipped, cancelled, and action_required runs."
                    ),
            })
        )
        .describe('Run history across the whole window, oldest first, zero-filled, bucketed by granularity.'),
    workflow_name: zod.string().describe('GitHub Actions workflow name.'),
    run_count: zod.number().describe('Total runs started in the window.'),
    success_rate: zod
        .number()
        .nullable()
        .describe('Fraction of completed runs that succeeded (0-1). Null if no completed runs.'),
    p50_seconds: zod
        .number()
        .nullable()
        .describe('Median duration of completed runs, in seconds. Null if none completed.'),
    p95_seconds: zod
        .number()
        .nullable()
        .describe('95th-percentile duration of completed runs, in seconds. Null if none completed.'),
    last_failure_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe("When the most recent failing run (conclusion 'failure' or 'timed_out') started, or null."),
    latest_run_failed: zod
        .boolean()
        .nullable()
        .describe(
            "Whether the most recent completed run was a decisive failure (conclusion 'failure' or 'timed_out'). Null when no run has completed in the window. Powers the OK\/RED status badge."
        ),
    latest_run_conclusion: zod
        .string()
        .nullable()
        .describe(
            "Raw conclusion of the most recent completed run ('success', 'cancelled', 'skipped', ...), so a real pass can be told from a non-failure non-success. Null when none completed."
        ),
    granularity: zod
        .string()
        .describe("Bucket width of the `buckets` series, chosen to fit the window: 'hour', 'day', or 'week'."),
    billable_minutes: zod
        .number()
        .nullish()
        .describe(
            "Billable (self-hosted) minutes over this workflow's jobs in the window. Null when the job-level source isn't synced."
        ),
    estimated_cost_usd: zod
        .number()
        .nullish()
        .describe(
            "Estimated cost in USD over this workflow's jobs in the window. Null when nothing was costable or the job source isn't synced."
        ),
})

export type WorkflowHealthItemApi = zod.input<typeof WorkflowHealthItemApi>
export type WorkflowHealthItemApiOutput = zod.output<typeof WorkflowHealthItemApi>

export const WorkflowJobApi = zod.object({
    id: zod.number().describe('GitHub Actions job id.'),
    run_id: zod.number().describe('The workflow run id this job belongs to.'),
    name: zod.string().describe('Job name.'),
    status: zod.string().describe("Raw job status: 'queued', 'in_progress', 'completed', etc."),
    conclusion: zod
        .string()
        .nullable()
        .describe("Job conclusion ('success', 'failure', 'cancelled', 'skipped', ...), or null while running."),
    started_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the job started, or null while still queued.'),
    completed_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the job completed, or null while still running.'),
    duration_seconds: zod.number().nullable().describe('Wall-clock duration in seconds; null until the job completes.'),
    runner_provider: zod
        .string()
        .describe("Where the job ran: 'github_hosted' (free for open source), 'self_hosted' (billable), or 'unknown'."),
    runner_label: zod
        .string()
        .describe("Runner tier the job ran on (e.g. '16-core' or 'ubuntu-latest'), or '' when unknown."),
    estimated_cost_usd: zod
        .number()
        .nullable()
        .describe(
            "Estimated cost in USD from runner tier + elapsed time; null when the tier is unknown or the job hasn't finished."
        ),
})

export type WorkflowJobApi = zod.input<typeof WorkflowJobApi>
export type WorkflowJobApiOutput = zod.output<typeof WorkflowJobApi>

export const WorkflowRunnerCostApi = zod.object({
    provider: zod.string().describe("'self_hosted' (billable), 'github_hosted' (free), or 'unknown'."),
    runner_label: zod.string().describe("Runner tier, e.g. '16-core' or 'ubuntu-latest'."),
    job_count: zod.number().describe('Jobs that ran on this tier for the workflow.'),
    billable_minutes: zod.number().describe('Billable minutes on this tier.'),
    estimated_cost_usd: zod
        .number()
        .nullable()
        .describe('Estimated cost in USD on this tier; null for non-billable (github-hosted\/non-Linux).'),
})

export type WorkflowRunnerCostApi = zod.input<typeof WorkflowRunnerCostApi>
export type WorkflowRunnerCostApiOutput = zod.output<typeof WorkflowRunnerCostApi>
