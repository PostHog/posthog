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

export const WorkflowHealthDayApi = zod.object({
    day: zod.iso.date().describe('UTC calendar day.'),
    run_count: zod.number().describe('Runs started that day.'),
    completed: zod.number().describe('Runs that completed that day.'),
    successes: zod.number().describe("Completed runs with conclusion 'success' that day."),
})

export type WorkflowHealthDayApi = zod.input<typeof WorkflowHealthDayApi>
export type WorkflowHealthDayApiOutput = zod.output<typeof WorkflowHealthDayApi>

export const WorkflowHealthItemApi = zod.object({
    repo: zod
        .object({
            provider: zod.string().describe("Code host provider, e.g. 'github'."),
            owner: zod.string().describe('Repository owner or organization.'),
            name: zod.string().describe('Repository name.'),
        })
        .describe('Repository the workflow runs in.'),
    daily: zod
        .array(
            zod.object({
                day: zod.iso.date().describe('UTC calendar day.'),
                run_count: zod.number().describe('Runs started that day.'),
                completed: zod.number().describe('Runs that completed that day.'),
                successes: zod.number().describe("Completed runs with conclusion 'success' that day."),
            })
        )
        .describe('Daily run history across the whole window, oldest first, zero-filled.'),
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
        .describe("When the most recent run with conclusion 'failure' started, or null."),
})

export type WorkflowHealthItemApi = zod.input<typeof WorkflowHealthItemApi>
export type WorkflowHealthItemApiOutput = zod.output<typeof WorkflowHealthItemApi>
