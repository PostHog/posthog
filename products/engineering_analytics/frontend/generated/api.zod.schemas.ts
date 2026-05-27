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

export const PullRequestStateEnumApi = zod
    .enum(['open', 'closed', 'merged'])
    .describe('\* `open` - OPEN\n\* `closed` - CLOSED\n\* `merged` - MERGED')

export type PullRequestStateEnumApi = zod.input<typeof PullRequestStateEnumApi>
export type PullRequestStateEnumApiOutput = zod.output<typeof PullRequestStateEnumApi>

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

export const BucketKindEnumApi = zod.enum(['all', 'author']).describe('\* `all` - ALL\n\* `author` - AUTHOR')

export type BucketKindEnumApi = zod.input<typeof BucketKindEnumApi>
export type BucketKindEnumApiOutput = zod.output<typeof BucketKindEnumApi>

export const TimeToMergeRowApi = zod.object({
    bucket: zod.string().describe("'all', or an author handle when grouping by author."),
    bucket_kind: zod
        .enum(['all', 'author'])
        .describe('\* `all` - ALL\n\* `author` - AUTHOR')
        .describe(
            "Whether this row aggregates all PRs ('all') or one author ('author').\n\n\* `all` - ALL\n\* `author` - AUTHOR"
        ),
    pr_count: zod.number().describe('Number of merged pull requests in the bucket.'),
    median_seconds: zod.number().describe('Median seconds from PR open to merge.'),
    p95_seconds: zod.number().describe('95th-percentile seconds from PR open to merge.'),
})

export type TimeToMergeRowApi = zod.input<typeof TimeToMergeRowApi>
export type TimeToMergeRowApiOutput = zod.output<typeof TimeToMergeRowApi>

export const TimeToMergeApi = zod.object({
    rows: zod
        .array(
            zod.object({
                bucket: zod.string().describe("'all', or an author handle when grouping by author."),
                bucket_kind: zod
                    .enum(['all', 'author'])
                    .describe('\* `all` - ALL\n\* `author` - AUTHOR')
                    .describe(
                        "Whether this row aggregates all PRs ('all') or one author ('author').\n\n\* `all` - ALL\n\* `author` - AUTHOR"
                    ),
                pr_count: zod.number().describe('Number of merged pull requests in the bucket.'),
                median_seconds: zod.number().describe('Median seconds from PR open to merge.'),
                p95_seconds: zod.number().describe('95th-percentile seconds from PR open to merge.'),
            })
        )
        .describe("One row for 'all', or one per author when grouping by author."),
    repo: zod
        .union([
            zod.object({
                provider: zod.string().describe("Code host provider, e.g. 'github'."),
                owner: zod.string().describe('Repository owner or organization.'),
                name: zod.string().describe('Repository name.'),
            }),
            zod.null(),
        ])
        .optional()
        .describe('Repository the result is labeled with, if a repo filter was supplied.'),
    date_from: zod.string().describe('Start of the window, echoed from the request (relative string or ISO8601).'),
    date_to: zod.string().nullable().describe("End of the window, echoed from the request; null means 'now'."),
    group_by_author: zod.boolean().describe('Whether rows are split per author.'),
    metric_quality: zod
        .enum(['precise', 'coarse', 'partial'])
        .describe('\* `precise` - PRECISE\n\* `coarse` - COARSE\n\* `partial` - PARTIAL')
        .optional()
        .describe(
            "Always 'coarse' — measures PR open to merge, combining draft and ready-for-review time.\n\n\* `precise` - PRECISE\n\* `coarse` - COARSE\n\* `partial` - PARTIAL"
        ),
})

export type TimeToMergeApi = zod.input<typeof TimeToMergeApi>
export type TimeToMergeApiOutput = zod.output<typeof TimeToMergeApi>

export const WorkflowReportRowApi = zod.object({
    workflow_name: zod.string().describe('GitHub Actions workflow name.'),
    total_runs: zod.number().describe('Number of runs of this workflow in the window.'),
    success_rate: zod.number().describe("Fraction of runs that concluded 'success', from 0.0 to 1.0."),
    median_duration_seconds: zod.number().describe('Median run duration in seconds.'),
    p95_duration_seconds: zod.number().describe('95th-percentile run duration in seconds.'),
    last_failed_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('Timestamp of the most recent failed run, or null if none failed in the window.'),
})

export type WorkflowReportRowApi = zod.input<typeof WorkflowReportRowApi>
export type WorkflowReportRowApiOutput = zod.output<typeof WorkflowReportRowApi>

export const WorkflowReportApi = zod.object({
    rows: zod
        .array(
            zod.object({
                workflow_name: zod.string().describe('GitHub Actions workflow name.'),
                total_runs: zod.number().describe('Number of runs of this workflow in the window.'),
                success_rate: zod.number().describe("Fraction of runs that concluded 'success', from 0.0 to 1.0."),
                median_duration_seconds: zod.number().describe('Median run duration in seconds.'),
                p95_duration_seconds: zod.number().describe('95th-percentile run duration in seconds.'),
                last_failed_at: zod.iso
                    .datetime({ offset: true })
                    .nullable()
                    .describe('Timestamp of the most recent failed run, or null if none failed in the window.'),
            })
        )
        .describe('Workflows in the window, slowest median duration first.'),
    repo: zod
        .union([
            zod.object({
                provider: zod.string().describe("Code host provider, e.g. 'github'."),
                owner: zod.string().describe('Repository owner or organization.'),
                name: zod.string().describe('Repository name.'),
            }),
            zod.null(),
        ])
        .optional()
        .describe('Repository the report is labeled with, if a repo filter was supplied.'),
    date_from: zod.string().describe('Start of the window, echoed from the request (relative string or ISO8601).'),
    date_to: zod.string().nullable().describe("End of the window, echoed from the request; null means 'now'."),
    metric_quality: zod
        .enum(['precise', 'coarse', 'partial'])
        .describe('\* `precise` - PRECISE\n\* `coarse` - COARSE\n\* `partial` - PARTIAL')
        .optional()
        .describe(
            "Always 'precise' — computed directly from CI run records.\n\n\* `precise` - PRECISE\n\* `coarse` - COARSE\n\* `partial` - PARTIAL"
        ),
})

export type WorkflowReportApi = zod.input<typeof WorkflowReportApi>
export type WorkflowReportApiOutput = zod.output<typeof WorkflowReportApi>
