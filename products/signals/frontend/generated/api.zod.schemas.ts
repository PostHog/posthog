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

export const PauseStateResponseApi = zod.object({
    paused_until: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('The timestamp the pipeline is paused until, or null if not paused\/not running.'),
})

export type PauseStateResponseApi = zod.input<typeof PauseStateResponseApi>
export type PauseStateResponseApiOutput = zod.output<typeof PauseStateResponseApi>

export const PaginatedPauseStateResponseListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(PauseStateResponseApi),
})

export type PaginatedPauseStateResponseListApi = zod.input<typeof PaginatedPauseStateResponseListApi>
export type PaginatedPauseStateResponseListApiOutput = zod.output<typeof PaginatedPauseStateResponseListApi>

export const PauseUntilRequestApi = zod.object({
    timestamp: zod.iso
        .datetime({ offset: true })
        .describe('Pause the grouping pipeline until this timestamp (ISO 8601).'),
})

export type PauseUntilRequestApi = zod.input<typeof PauseUntilRequestApi>
export type PauseUntilRequestApiOutput = zod.output<typeof PauseUntilRequestApi>

export const PauseResponseApi = zod.object({
    status: zod.string().describe("Always 'paused'."),
    paused_until: zod.iso.datetime({ offset: true }).describe('The timestamp the pipeline is paused until.'),
})

export type PauseResponseApi = zod.input<typeof PauseResponseApi>
export type PauseResponseApiOutput = zod.output<typeof PauseResponseApi>

export const SignalReportStatusEnumApi = zod
    .enum([
        'potential',
        'candidate',
        'in_progress',
        'pending_input',
        'ready',
        'resolved',
        'failed',
        'deleted',
        'suppressed',
    ])
    .describe(
        '\* `potential` - Potential\n\* `candidate` - Candidate\n\* `in_progress` - In Progress\n\* `pending_input` - Pending Input\n\* `ready` - Ready\n\* `resolved` - Resolved\n\* `failed` - Failed\n\* `deleted` - Deleted\n\* `suppressed` - Suppressed'
    )

export type SignalReportStatusEnumApi = zod.input<typeof SignalReportStatusEnumApi>
export type SignalReportStatusEnumApiOutput = zod.output<typeof SignalReportStatusEnumApi>

export const SizeEnumApi = zod
    .enum(['small', 'medium', 'large'])
    .describe('\* `small` - small\n\* `medium` - medium\n\* `large` - large')

export type SizeEnumApi = zod.input<typeof SizeEnumApi>
export type SizeEnumApiOutput = zod.output<typeof SizeEnumApi>

export const reportChartApiChartIdMax = 100

export const reportChartApiTitleMax = 200

export const reportChartApiCaptionMax = 500

export const ReportChartApi = zod
    .object({
        chart_id: zod
            .string()
            .max(reportChartApiChartIdMax)
            .describe(
                "Stable slug for this chart within the report (lowercase letters, numbers, underscores, hyphens; must start with a letter or number). Reference it from `summary` as a markdown link with a `chart:` target — `[Daily signups](chart:signups-drop)` — to place the chart at that point in the body. A chart you don't reference still renders, below the summary."
            ),
        title: zod.string().max(reportChartApiTitleMax).describe('Short heading shown above the chart.'),
        query: zod
            .unknown()
            .describe(
                'The query node to render. `kind` must be `InsightVizNode` (an ad-hoc product analytics chart), `DataVisualizationNode` (a SQL series — a `HogQLQuery` source plus a `display`), or `SavedInsightNode` (an existing insight by `shortId`). Pin the window to absolute dates where the node supports it, so the reader sees the data you wrote about rather than whatever a relative range resolves to when they open the report.'
            ),
        caption: zod
            .string()
            .max(reportChartApiCaptionMax)
            .nullish()
            .describe('Optional one-line note on what to look at in the chart.'),
        size: zod
            .union([SizeEnumApi, zod.null()])
            .optional()
            .describe(
                'How much height the chart gets: `small` for a single number or a short series, `medium` for an ordinary graph, `large` when there are rows or a grid to read (retention, paths, a wide breakdown). Leave it out unless the default looks wrong — the inbox sizes a chart from its query, and two charts referenced from the same paragraph sit side by side.\n\n\* `small` - small\n\* `medium` - medium\n\* `large` - large'
            ),
    })
    .describe('One chart attached to a report — rendered in the inbox and referenceable from the summary.')

export type ReportChartApi = zod.input<typeof ReportChartApi>
export type ReportChartApiOutput = zod.output<typeof ReportChartApi>

export const SignalReportRefundReasonEnumApi = zod
    .enum(['pr_incorrect', 'pr_not_useful', 'duplicate', 'other'])
    .describe(
        '\* `pr_incorrect` - PR incorrect\n\* `pr_not_useful` - PR not useful\n\* `duplicate` - Duplicate\n\* `other` - Other'
    )

export type SignalReportRefundReasonEnumApi = zod.input<typeof SignalReportRefundReasonEnumApi>
export type SignalReportRefundReasonEnumApiOutput = zod.output<typeof SignalReportRefundReasonEnumApi>

export const BillingPathEnumApi = zod
    .enum(['excluded', 'credited'])
    .describe('\* `excluded` - Excluded\n\* `credited` - Credited')

export type BillingPathEnumApi = zod.input<typeof BillingPathEnumApi>
export type BillingPathEnumApiOutput = zod.output<typeof BillingPathEnumApi>

export const signalReportRefundApiCreditAmountUsdRegExp = new RegExp('^-?\\d{0,8}(?:\\.\\d{0,2})?$')

export const SignalReportRefundApi = zod.object({
    id: zod.uuid(),
    reason: SignalReportRefundReasonEnumApi.describe(
        'Why the user refunded this PR (feeds the refund review).\n\n\* `pr_incorrect` - PR incorrect\n\* `pr_not_useful` - PR not useful\n\* `duplicate` - Duplicate\n\* `other` - Other'
    ),
    note: zod.string().describe('Optional free-form note captured with the refund.'),
    billing_path: BillingPathEnumApi.describe(
        "How the refund was executed, frozen at refund time: 'excluded' (same UTC day as the billable PR run — the report never reaches billing) or 'credited' (billing issues a Stripe customer-balance credit).\n\n\* `excluded` - Excluded\n\* `credited` - Credited"
    ),
    credits: zod.number().describe('Signals credits refunded (flat per-PR charge snapshot; 1 credit = $0.01).'),
    pr_url: zod.string().describe("The refunded implementation PR's GitHub URL, snapshotted at refund time."),
    pr_run_created_at: zod.iso
        .datetime({ offset: true })
        .describe('When the first billable PR run was created — the charge this reverses.'),
    credit_amount_usd: zod
        .stringFormat('decimal', signalReportRefundApiCreditAmountUsdRegExp)
        .nullable()
        .describe(
            "USD amount the billing service credited (credited path only). Null until the sync completes; '0.00' is a legitimate outcome (e.g. the PR was inside the free tier)."
        ),
    billing_synced: zod
        .boolean()
        .describe(
            'Whether the billing service has acknowledged this refund. Always relevant for the credited path (the Stripe credit is issued asynchronously); excluded-path refunds need no billing sync and report false.'
        ),
    created_at: zod.iso.datetime({ offset: true }).describe('When the refund was created.'),
})

export type SignalReportRefundApi = zod.input<typeof SignalReportRefundApi>
export type SignalReportRefundApiOutput = zod.output<typeof SignalReportRefundApi>

export const RefundIneligibilityReasonEnumApi = zod.enum([
    'already_refunded',
    'billing_exempt',
    'no_billable_pr',
    'out_of_period',
])

export type RefundIneligibilityReasonEnumApi = zod.input<typeof RefundIneligibilityReasonEnumApi>
export type RefundIneligibilityReasonEnumApiOutput = zod.output<typeof RefundIneligibilityReasonEnumApi>

export const BillingExemptReasonEnumApi = zod
    .enum(['posthog_health_check', 'posthog_onboarding', 'posthog_system'])
    .describe(
        '\* `posthog_health_check` - PostHog health check\n\* `posthog_onboarding` - PostHog onboarding\n\* `posthog_system` - PostHog system'
    )

export type BillingExemptReasonEnumApi = zod.input<typeof BillingExemptReasonEnumApi>
export type BillingExemptReasonEnumApiOutput = zod.output<typeof BillingExemptReasonEnumApi>

export const signalReportApiIsSuggestedReviewerDefault = false

export const SignalReportApi = zod.object({
    id: zod.uuid(),
    title: zod.string().nullable(),
    summary: zod.string().nullable(),
    status: SignalReportStatusEnumApi,
    total_weight: zod.number(),
    signal_count: zod.number(),
    signals_at_run: zod.number(),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
    artefact_count: zod.number(),
    charts: zod
        .array(ReportChartApi)
        .describe(
            'Charts the report shows, in the order they were written. The summary places one with a `[label](chart:<chart_id>)` link; the rest render below it.'
        ),
    priority: zod.string().nullable().describe('P0–P4 from the latest priority judgment artefact (when present).'),
    actionability: zod
        .string()
        .nullable()
        .describe('Actionability choice from the latest actionability judgment artefact (when present).'),
    already_addressed: zod
        .boolean()
        .nullable()
        .describe(
            'Whether the issue is already being handled — fixed in recent changes, or with a fix in flight (an open PR, a recently active branch, an assigned \/ in-progress issue or agent task) — from the actionability judgment artefact.'
        ),
    dismissal_reason: zod
        .string()
        .nullable()
        .describe('Reason code from the latest dismissal artefact, set when the report was suppressed (when present).'),
    dismissal_note: zod
        .string()
        .nullable()
        .describe('Free-form note captured alongside the dismissal reason (when present).'),
    is_suggested_reviewer: zod.boolean().default(signalReportApiIsSuggestedReviewerDefault),
    source_products: zod
        .array(zod.string())
        .describe('Distinct source products contributing signals to this report (from ClickHouse).'),
    scout_name: zod
        .string()
        .nullable()
        .describe(
            'skill_name slug of the scout that authored this report, when scout-authored (from ClickHouse); null otherwise.'
        ),
    implementation_pr_url: zod
        .string()
        .nullable()
        .describe('PR URL from the latest implementation task run, if available.'),
    implementation_pr_merged: zod
        .boolean()
        .describe(
            "Whether that implementation PR is merged, per the GitHub webhook. False when there is no PR or it hasn't merged. Report status doesn't imply this: a resolved report may have been resolved directly, without a merged PR."
        ),
    refund: zod
        .union([SignalReportRefundApi, zod.null()])
        .describe("The report's PR refund, when one exists. One refund per report, ever."),
    refund_ineligibility_reason: zod
        .union([RefundIneligibilityReasonEnumApi, zod.null()])
        .describe(
            "Why refunding this report's PR would be rejected right now, or null when a refund would be accepted (see the field's schema for the reason values)."
        ),
    billing_exempt_reason: zod
        .union([BillingExemptReasonEnumApi, zod.null()])
        .describe(
            'Non-null when this report is system-marked never-billable (PostHog-system origin, e.g. a health-check scout finding) — its implementation PRs are free and cannot be refunded because nothing was charged.\n\n\* `posthog_health_check` - PostHog health check\n\* `posthog_onboarding` - PostHog onboarding\n\* `posthog_system` - PostHog system'
        ),
})

export type SignalReportApi = zod.input<typeof SignalReportApi>
export type SignalReportApiOutput = zod.output<typeof SignalReportApi>

export const PaginatedSignalReportListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(SignalReportApi),
})

export type PaginatedSignalReportListApi = zod.input<typeof PaginatedSignalReportListApi>
export type PaginatedSignalReportListApiOutput = zod.output<typeof PaginatedSignalReportListApi>

export const patchedSignalReportContentUpdateApiTitleMax = 300

export const patchedSignalReportContentUpdateApiSummaryMax = 10000

export const PatchedSignalReportContentUpdateApi = zod
    .object({
        title: zod
            .string()
            .min(1)
            .max(patchedSignalReportContentUpdateApiTitleMax)
            .optional()
            .describe('New human-facing title for the report. Omit to leave the title unchanged.'),
        summary: zod
            .string()
            .min(1)
            .max(patchedSignalReportContentUpdateApiSummaryMax)
            .optional()
            .describe(
                "New summary (the report's description) explaining what the report is about. Omit to leave the summary unchanged."
            ),
    })
    .describe(
        'Editable human-facing fields on a signal report (PATCH).\n\nBoth fields are optional so a caller can change either independently, but at least one\nmust be supplied. Every other report field — status, weights, judgments — is owned by the\nsignals pipeline and is deliberately not writable here.'
    )

export type PatchedSignalReportContentUpdateApi = zod.input<typeof PatchedSignalReportContentUpdateApi>
export type PatchedSignalReportContentUpdateApiOutput = zod.output<typeof PatchedSignalReportContentUpdateApi>

export const PullRequestCheckApi = zod
    .object({
        name: zod.string().describe('Check run name or status context.'),
        status: zod.string().nullable().describe("Lifecycle state: 'queued', 'in_progress', or 'completed'."),
        conclusion: zod
            .string()
            .nullable()
            .describe(
                "Outcome once completed: 'success', 'failure', 'neutral', 'cancelled', 'skipped', 'timed_out', or 'action_required'. Null while still running."
            ),
        url: zod.string().nullable().describe('Link to the check run \/ status detail on GitHub.'),
    })
    .describe(
        "One CI check on a pull request's head commit — a GitHub Actions check run or a legacy commit\nstatus, normalized to a common shape."
    )

export type PullRequestCheckApi = zod.input<typeof PullRequestCheckApi>
export type PullRequestCheckApiOutput = zod.output<typeof PullRequestCheckApi>

export const PullRequestChecksResponseApi = zod
    .object({
        checks: zod.array(PullRequestCheckApi),
    })
    .describe("Response for the PR checks endpoint — the CI status of a report's implementation PR.")

export type PullRequestChecksResponseApi = zod.input<typeof PullRequestChecksResponseApi>
export type PullRequestChecksResponseApiOutput = zod.output<typeof PullRequestChecksResponseApi>

export const CommentTypeEnumApi = zod
    .enum(['conversation', 'review'])
    .describe('\* `conversation` - conversation\n\* `review` - review')

export type CommentTypeEnumApi = zod.input<typeof CommentTypeEnumApi>
export type CommentTypeEnumApiOutput = zod.output<typeof CommentTypeEnumApi>

export const SideEnumApi = zod.enum(['LEFT', 'RIGHT']).describe('\* `LEFT` - LEFT\n\* `RIGHT` - RIGHT')

export type SideEnumApi = zod.input<typeof SideEnumApi>
export type SideEnumApiOutput = zod.output<typeof SideEnumApi>

export const PullRequestCommentReactionApi = zod
    .object({
        id: zod.string().describe('GitHub reaction id (needed to remove it).'),
        content: zod
            .string()
            .describe("Reaction key: '+1', '-1', 'laugh', 'hooray', 'confused', 'heart', 'rocket', or 'eyes'."),
        user_login: zod.string().nullable().describe('GitHub login of the user who added the reaction.'),
    })
    .describe("One emoji reaction on a review comment, with the reactor so the viewer's own can be toggled.")

export type PullRequestCommentReactionApi = zod.input<typeof PullRequestCommentReactionApi>
export type PullRequestCommentReactionApiOutput = zod.output<typeof PullRequestCommentReactionApi>

export const PullRequestCommentApi = zod
    .object({
        id: zod.string().describe('GitHub comment id.'),
        author: zod.string().nullable().describe("Comment author's GitHub login."),
        author_avatar_url: zod.string().nullable().describe("Author's GitHub avatar URL."),
        body: zod.string().describe('Comment body (GitHub-flavored markdown).'),
        created_at: zod.string().nullable().describe('ISO 8601 creation timestamp.'),
        url: zod.string().nullable().describe('Link to the comment on GitHub.'),
        comment_type: CommentTypeEnumApi.describe(
            "'conversation' for a PR discussion comment, 'review' for an inline code-review comment.\n\n\* `conversation` - conversation\n\* `review` - review"
        ),
        path: zod.string().nullable().describe('File path the review comment is anchored to (review comments only).'),
        line: zod
            .number()
            .nullable()
            .describe(
                'Line in the diff the review comment is anchored to — the end line for multi-line comments (review comments only; null when the comment is outdated relative to the PR head).'
            ),
        start_line: zod
            .number()
            .nullable()
            .describe("First line of a multi-line review comment's range (review comments only)."),
        side: zod
            .union([SideEnumApi, zod.null()])
            .describe(
                "Diff side the review comment is anchored to: 'LEFT' = deletions, 'RIGHT' = additions (review comments only).\n\n\* `LEFT` - LEFT\n\* `RIGHT` - RIGHT"
            ),
        diff_hunk: zod
            .string()
            .nullable()
            .describe('Diff hunk excerpt the review comment applies to (review comments only).'),
        in_reply_to_id: zod
            .string()
            .nullable()
            .describe(
                'Id of the thread root comment this one replies to; null for thread roots and conversation comments.'
            ),
        commit_id: zod
            .string()
            .nullable()
            .describe('SHA of the commit the review comment was made against (review comments only).'),
        reactions: zod
            .array(PullRequestCommentReactionApi)
            .describe('Emoji reactions on this review comment, one entry per reactor.'),
    })
    .describe('One comment on a pull request — a conversation comment or an inline review comment.')

export type PullRequestCommentApi = zod.input<typeof PullRequestCommentApi>
export type PullRequestCommentApiOutput = zod.output<typeof PullRequestCommentApi>

export const PullRequestCommentsResponseApi = zod
    .object({
        comments: zod.array(PullRequestCommentApi),
    })
    .describe('Response for the PR comments endpoint — conversation and review comments merged chronologically.')

export type PullRequestCommentsResponseApi = zod.input<typeof PullRequestCommentsResponseApi>
export type PullRequestCommentsResponseApiOutput = zod.output<typeof PullRequestCommentsResponseApi>

export const pullRequestReviewCommentCreateApiBodyMax = 65536

export const pullRequestReviewCommentCreateApiInReplyToRegExp = new RegExp('^[0-9]+$')

export const PullRequestReviewCommentCreateApi = zod
    .object({
        body: zod
            .string()
            .max(pullRequestReviewCommentCreateApiBodyMax)
            .describe('Comment body (GitHub-flavored markdown).'),
        in_reply_to: zod
            .string()
            .regex(pullRequestReviewCommentCreateApiInReplyToRegExp)
            .nullish()
            .describe('Numeric id of the thread root comment to reply to. When set, path\/line\/side are ignored.'),
        path: zod
            .string()
            .nullish()
            .describe('File path to anchor a new comment thread to (required when starting a new thread).'),
        line: zod
            .number()
            .min(1)
            .nullish()
            .describe('Diff line to anchor a new comment thread to (required when starting a new thread).'),
        side: zod
            .union([SideEnumApi, zod.null()])
            .optional()
            .describe(
                "Diff side of the anchor line: 'LEFT' = deletions, 'RIGHT' = additions. Defaults to 'RIGHT'.\n\n\* `LEFT` - LEFT\n\* `RIGHT` - RIGHT"
            ),
    })
    .describe(
        'Request body for posting an inline PR review comment as the requesting user.\n\nTwo shapes: a reply to an existing thread (only `body` + `in_reply_to`), or a new\nthread on a diff line (`body` + `path` + `line`, optionally `side`).'
    )

export type PullRequestReviewCommentCreateApi = zod.input<typeof PullRequestReviewCommentCreateApi>
export type PullRequestReviewCommentCreateApiOutput = zod.output<typeof PullRequestReviewCommentCreateApi>

export const PullRequestReviewCommentCreateResponseApi = zod
    .object({
        comment: PullRequestCommentApi,
    })
    .describe('Response after posting a review comment — the created comment in the normalized PR-comment shape.')

export type PullRequestReviewCommentCreateResponseApi = zod.input<typeof PullRequestReviewCommentCreateResponseApi>
export type PullRequestReviewCommentCreateResponseApiOutput = zod.output<
    typeof PullRequestReviewCommentCreateResponseApi
>

export const patchedPullRequestReviewCommentUpdateApiBodyMax = 65536

export const PatchedPullRequestReviewCommentUpdateApi = zod
    .object({
        body: zod
            .string()
            .max(patchedPullRequestReviewCommentUpdateApiBodyMax)
            .optional()
            .describe('New comment body (GitHub-flavored markdown).'),
    })
    .describe("Request body for editing a review comment's markdown body.")

export type PatchedPullRequestReviewCommentUpdateApi = zod.input<typeof PatchedPullRequestReviewCommentUpdateApi>
export type PatchedPullRequestReviewCommentUpdateApiOutput = zod.output<typeof PatchedPullRequestReviewCommentUpdateApi>

export const ContentEnumApi = zod
    .enum(['+1', '-1', 'laugh', 'hooray', 'confused', 'heart', 'rocket', 'eyes'])
    .describe(
        '\* `+1` - +1\n\* `-1` - -1\n\* `laugh` - laugh\n\* `hooray` - hooray\n\* `confused` - confused\n\* `heart` - heart\n\* `rocket` - rocket\n\* `eyes` - eyes'
    )

export type ContentEnumApi = zod.input<typeof ContentEnumApi>
export type ContentEnumApiOutput = zod.output<typeof ContentEnumApi>

export const PullRequestReviewCommentReactionCreateApi = zod
    .object({
        content: ContentEnumApi.describe(
            "Reaction to add: one of '+1', '-1', 'laugh', 'hooray', 'confused', 'heart', 'rocket', 'eyes'.\n\n\* `+1` - +1\n\* `-1` - -1\n\* `laugh` - laugh\n\* `hooray` - hooray\n\* `confused` - confused\n\* `heart` - heart\n\* `rocket` - rocket\n\* `eyes` - eyes"
        ),
    })
    .describe('Request body for adding an emoji reaction to a review comment.')

export type PullRequestReviewCommentReactionCreateApi = zod.input<typeof PullRequestReviewCommentReactionCreateApi>
export type PullRequestReviewCommentReactionCreateApiOutput = zod.output<
    typeof PullRequestReviewCommentReactionCreateApi
>

export const PullRequestReviewCommentReactionCreateResponseApi = zod
    .object({
        reaction: PullRequestCommentReactionApi,
    })
    .describe('Response after adding a reaction — the created reaction, so the frontend can track its id.')

export type PullRequestReviewCommentReactionCreateResponseApi = zod.input<
    typeof PullRequestReviewCommentReactionCreateResponseApi
>
export type PullRequestReviewCommentReactionCreateResponseApiOutput = zod.output<
    typeof PullRequestReviewCommentReactionCreateResponseApi
>

export const signalReportRefundRequestApiNoteMax = 4000

export const SignalReportRefundRequestApi = zod.object({
    reason: SignalReportRefundReasonEnumApi.describe(
        "Why this PR is being refunded. One of: pr_incorrect (the PR doesn't address what the report promised), pr_not_useful (technically fine but not worth paying for), duplicate (covers work already charged elsewhere), other. Required — refund reviews key on it.\n\n\* `pr_incorrect` - PR incorrect\n\* `pr_not_useful` - PR not useful\n\* `duplicate` - Duplicate\n\* `other` - Other"
    ),
    note: zod
        .string()
        .max(signalReportRefundRequestApiNoteMax)
        .optional()
        .describe(
            "Optional free-form context for the refund; stored on the refund and echoed in the report's dismissal artefact. Capped at 4000 characters."
        ),
})

export type SignalReportRefundRequestApi = zod.input<typeof SignalReportRefundRequestApi>
export type SignalReportRefundRequestApiOutput = zod.output<typeof SignalReportRefundRequestApi>

export const signalReportRefundResponseApiCreditAmountUsdRegExp = new RegExp('^-?\\d{0,8}(?:\\.\\d{0,2})?$')
export const signalReportRefundResponseApiAlreadyRefundedDefault = false

export const SignalReportRefundResponseApi = zod.object({
    id: zod.uuid(),
    reason: SignalReportRefundReasonEnumApi.describe(
        'Why the user refunded this PR (feeds the refund review).\n\n\* `pr_incorrect` - PR incorrect\n\* `pr_not_useful` - PR not useful\n\* `duplicate` - Duplicate\n\* `other` - Other'
    ),
    note: zod.string().describe('Optional free-form note captured with the refund.'),
    billing_path: BillingPathEnumApi.describe(
        "How the refund was executed, frozen at refund time: 'excluded' (same UTC day as the billable PR run — the report never reaches billing) or 'credited' (billing issues a Stripe customer-balance credit).\n\n\* `excluded` - Excluded\n\* `credited` - Credited"
    ),
    credits: zod.number().describe('Signals credits refunded (flat per-PR charge snapshot; 1 credit = $0.01).'),
    pr_url: zod.string().describe("The refunded implementation PR's GitHub URL, snapshotted at refund time."),
    pr_run_created_at: zod.iso
        .datetime({ offset: true })
        .describe('When the first billable PR run was created — the charge this reverses.'),
    credit_amount_usd: zod
        .stringFormat('decimal', signalReportRefundResponseApiCreditAmountUsdRegExp)
        .nullable()
        .describe(
            "USD amount the billing service credited (credited path only). Null until the sync completes; '0.00' is a legitimate outcome (e.g. the PR was inside the free tier)."
        ),
    billing_synced: zod
        .boolean()
        .describe(
            'Whether the billing service has acknowledged this refund. Always relevant for the credited path (the Stripe credit is issued asynchronously); excluded-path refunds need no billing sync and report false.'
        ),
    created_at: zod.iso.datetime({ offset: true }).describe('When the refund was created.'),
    already_refunded: zod
        .boolean()
        .default(signalReportRefundResponseApiAlreadyRefundedDefault)
        .describe(
            'True when the report already had a refund and that existing refund is returned unchanged — refunds are one-per-report and repeat calls are idempotent.'
        ),
})

export type SignalReportRefundResponseApi = zod.input<typeof SignalReportRefundResponseApi>
export type SignalReportRefundResponseApiOutput = zod.output<typeof SignalReportRefundResponseApi>

export const ReportSignalsResponseApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ReportSignalsResponseApi = zod.input<typeof ReportSignalsResponseApi>
export type ReportSignalsResponseApiOutput = zod.output<typeof ReportSignalsResponseApi>

export const SignalReportStateEnumApi = zod
    .enum(['suppressed', 'potential', 'resolved'])
    .describe('\* `suppressed` - suppressed\n\* `potential` - potential\n\* `resolved` - resolved')

export type SignalReportStateEnumApi = zod.input<typeof SignalReportStateEnumApi>
export type SignalReportStateEnumApiOutput = zod.output<typeof SignalReportStateEnumApi>

export const DismissalReasonEnumApi = zod
    .enum(['already_fixed', 'report_unclear', 'analysis_wrong', 'wontfix_intentional', 'wontfix_irrelevant', 'other'])
    .describe(
        "\* `already_fixed` - Already fixed\n\* `report_unclear` - Report is unclear to me\n\* `analysis_wrong` - Agent's analysis is wrong\n\* `wontfix_intentional` - Won't fix - intentional behavior\n\* `wontfix_irrelevant` - Won't fix - issue is real but insignificant\n\* `other` - Something else…"
    )

export type DismissalReasonEnumApi = zod.input<typeof DismissalReasonEnumApi>
export type DismissalReasonEnumApiOutput = zod.output<typeof DismissalReasonEnumApi>

export const signalReportStateRequestApiDismissalNoteMax = 4000

export const signalReportStateRequestApiSnoozeForMax = 100000

export const SignalReportStateRequestApi = zod.object({
    state: SignalReportStateEnumApi.describe(
        "Target state for the report. Use 'suppressed' to dismiss the report from the inbox, 'potential' to snooze\/reopen it for later review, or 'resolved' when the work this report asked for has been done. Resolving is only allowed from a researched status (ready or pending_input) or a suppressed report; other statuses return 409 (skipped in bulk).\n\n\* `suppressed` - suppressed\n\* `potential` - potential\n\* `resolved` - resolved"
    ),
    dismissal_reason: DismissalReasonEnumApi.optional().describe(
        "Optional canonical reason code for the dismissal. Must be one of: already_fixed, report_unclear, analysis_wrong, wontfix_intentional, wontfix_irrelevant, other — these match the inbox UI so the rationale renders as a labelled chip rather than a raw code. When the work this report asked for is done, the honest transition is state='resolved' (the reason\/note records why). Reserve 'already_fixed' with state='potential' (snooze\/restore) for \"fixed by something else \/ might recur\" cases, so the report reappears if the issue comes back. Use 'other' together with a dismissal_note for anything that doesn't fit a code.\n\n\* `already_fixed` - Already fixed\n\* `report_unclear` - Report is unclear to me\n\* `analysis_wrong` - Agent's analysis is wrong\n\* `wontfix_intentional` - Won't fix - intentional behavior\n\* `wontfix_irrelevant` - Won't fix - issue is real but insignificant\n\* `other` - Something else…"
    ),
    dismissal_note: zod
        .string()
        .max(signalReportStateRequestApiDismissalNoteMax)
        .optional()
        .describe('Optional free-form note explaining the dismissal. Capped at 4000 characters.'),
    snooze_for: zod
        .number()
        .min(1)
        .max(signalReportStateRequestApiSnoozeForMax)
        .optional()
        .describe(
            "Optional, only honored when state is 'potential'. Number of additional signals the report must accumulate before it is re-promoted into the pipeline — effectively snoozing it until then. Omit to let the report re-enter the pipeline on the next matching signal."
        ),
})

export type SignalReportStateRequestApi = zod.input<typeof SignalReportStateRequestApi>
export type SignalReportStateRequestApiOutput = zod.output<typeof SignalReportStateRequestApi>

export const SignalReportArtefactTypeEnumApi = zod
    .enum([
        'video_segment',
        'safety_judgment',
        'actionability_judgment',
        'priority_judgment',
        'signal_finding',
        'repo_selection',
        'suggested_reviewers',
        'dismissal',
        'code_reference',
        'commit',
        'task_run',
        'note',
        'title_change',
        'summary_change',
        'code_review',
        'related_to',
    ])
    .describe(
        '\* `video_segment` - Video Segment\n\* `safety_judgment` - Safety Judgment\n\* `actionability_judgment` - Actionability Judgment\n\* `priority_judgment` - Priority Judgment\n\* `signal_finding` - Signal Finding\n\* `repo_selection` - Repo Selection\n\* `suggested_reviewers` - Suggested Reviewers\n\* `dismissal` - Dismissal\n\* `code_reference` - Code Reference\n\* `commit` - Commit\n\* `task_run` - Task Run\n\* `note` - Note\n\* `title_change` - Title Change\n\* `summary_change` - Summary Change\n\* `code_review` - Code Review\n\* `related_to` - Related To'
    )

export type SignalReportArtefactTypeEnumApi = zod.input<typeof SignalReportArtefactTypeEnumApi>
export type SignalReportArtefactTypeEnumApiOutput = zod.output<typeof SignalReportArtefactTypeEnumApi>

export const _UserApi = zod.object({
    id: zod.number(),
    uuid: zod.uuid(),
    first_name: zod.string(),
    last_name: zod.string(),
    email: zod.email(),
})

export type _UserApi = zod.input<typeof _UserApi>
export type _UserApiOutput = zod.output<typeof _UserApi>

export const SignalReportArtefactApi = zod.object({
    id: zod.uuid(),
    type: SignalReportArtefactTypeEnumApi,
    content: zod.union([zod.record(zod.string(), zod.unknown()), zod.array(zod.unknown())]),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
    created_by: zod
        .union([_UserApi, zod.null()])
        .describe('User the artefact is attributed to, when a user produced it. Null for task\/system writes.'),
    task_id: zod
        .uuid()
        .nullable()
        .describe('Task the artefact is attributed to, when an agent produced it. Null for user\/system writes.'),
})

export type SignalReportArtefactApi = zod.input<typeof SignalReportArtefactApi>
export type SignalReportArtefactApiOutput = zod.output<typeof SignalReportArtefactApi>

export const PaginatedSignalReportArtefactListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(SignalReportArtefactApi),
})

export type PaginatedSignalReportArtefactListApi = zod.input<typeof PaginatedSignalReportArtefactListApi>
export type PaginatedSignalReportArtefactListApiOutput = zod.output<typeof PaginatedSignalReportArtefactListApi>

export const SignalReportArtefactLogCreateApi = zod
    .object({
        artefact_type: zod
            .string()
            .describe(
                "The artefact type. One of: actionability_judgment, code_reference, commit, dismissal, note, priority_judgment, related_to, repo_selection, safety_judgment, signal_finding, suggested_reviewers, task_run. Log types accumulate; status types (safety_judgment, actionability_judgment, priority_judgment, repo_selection, suggested_reviewers) are latest-wins — appending a new version supersedes the previous one as the report's canonical status."
            ),
        content: zod
            .unknown()
            .describe(
                'The artefact payload as a JSON object or array; shape depends on artefact_type and is validated against its schema.'
            ),
    })
    .describe(
        "Body for appending an artefact to a report.\n\nEverything is append-only: log artefacts accumulate, status artefacts supersede the previous\nversion (latest-wins). The `content` shape depends on `artefact_type` and is validated\nagainst the type's schema (see `products\/signals\/backend\/artefact_schemas.py`)."
    )

export type SignalReportArtefactLogCreateApi = zod.input<typeof SignalReportArtefactLogCreateApi>
export type SignalReportArtefactLogCreateApiOutput = zod.output<typeof SignalReportArtefactLogCreateApi>

export const SignalReportArtefactWriteResponseApi = zod
    .object({
        id: zod.uuid().describe("The artefact's unique id."),
        report_id: zod.uuid().describe('The id of the report this artefact belongs to.'),
        type: zod.string().describe('The artefact type.'),
        content: zod.unknown().describe('The artefact payload, parsed from storage.'),
        created_at: zod.iso.datetime({ offset: true }).describe('When the artefact was created.'),
        updated_at: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe(
                'When the artefact was last written — set on creation and refreshed on each edit. Null only for rows created before this field existed.'
            ),
        task_id: zod
            .uuid()
            .nullable()
            .describe('Task the artefact is attributed to, when an agent produced it. Null for user writes.'),
    })
    .describe('Response shape for the log-artefact create\/update endpoints — echoes the stored row.')

export type SignalReportArtefactWriteResponseApi = zod.input<typeof SignalReportArtefactWriteResponseApi>
export type SignalReportArtefactWriteResponseApiOutput = zod.output<typeof SignalReportArtefactWriteResponseApi>

export const PatchedSignalReportArtefactLogUpdateApi = zod
    .object({
        content: zod
            .unknown()
            .optional()
            .describe("The new artefact payload as a JSON object or array, matching the artefact type's schema."),
    })
    .describe(
        "Body for replacing the content of an existing artefact (addressed by id).\n\nPer-type schema validation happens in the view, which knows the artefact's type."
    )

export type PatchedSignalReportArtefactLogUpdateApi = zod.input<typeof PatchedSignalReportArtefactLogUpdateApi>
export type PatchedSignalReportArtefactLogUpdateApiOutput = zod.output<typeof PatchedSignalReportArtefactLogUpdateApi>

export const CommitDiffResponseApi = zod
    .object({
        diff: zod
            .string()
            .describe(
                'Unified diff (patch) text of the branch against the repository default branch, from the GitHub compare API.'
            ),
        truncated: zod.boolean().describe('True when the diff was too large to return in full and has been truncated.'),
    })
    .describe(
        "Response for the `commit` artefact diff endpoint — the commit's branch rendered against the\nrepository default branch."
    )

export type CommitDiffResponseApi = zod.input<typeof CommitDiffResponseApi>
export type CommitDiffResponseApiOutput = zod.output<typeof CommitDiffResponseApi>

export const signalReportBulkStateRequestApiDismissalNoteMax = 4000

export const signalReportBulkStateRequestApiSnoozeForMax = 100000

export const signalReportBulkStateRequestApiIdsMax = 100

export const SignalReportBulkStateRequestApi = zod.object({
    state: SignalReportStateEnumApi.describe(
        "Target state for the report. Use 'suppressed' to dismiss the report from the inbox, 'potential' to snooze\/reopen it for later review, or 'resolved' when the work this report asked for has been done. Resolving is only allowed from a researched status (ready or pending_input) or a suppressed report; other statuses return 409 (skipped in bulk).\n\n\* `suppressed` - suppressed\n\* `potential` - potential\n\* `resolved` - resolved"
    ),
    dismissal_reason: DismissalReasonEnumApi.optional().describe(
        "Optional canonical reason code for the dismissal. Must be one of: already_fixed, report_unclear, analysis_wrong, wontfix_intentional, wontfix_irrelevant, other — these match the inbox UI so the rationale renders as a labelled chip rather than a raw code. When the work this report asked for is done, the honest transition is state='resolved' (the reason\/note records why). Reserve 'already_fixed' with state='potential' (snooze\/restore) for \"fixed by something else \/ might recur\" cases, so the report reappears if the issue comes back. Use 'other' together with a dismissal_note for anything that doesn't fit a code.\n\n\* `already_fixed` - Already fixed\n\* `report_unclear` - Report is unclear to me\n\* `analysis_wrong` - Agent's analysis is wrong\n\* `wontfix_intentional` - Won't fix - intentional behavior\n\* `wontfix_irrelevant` - Won't fix - issue is real but insignificant\n\* `other` - Something else…"
    ),
    dismissal_note: zod
        .string()
        .max(signalReportBulkStateRequestApiDismissalNoteMax)
        .optional()
        .describe('Optional free-form note explaining the dismissal. Capped at 4000 characters.'),
    snooze_for: zod
        .number()
        .min(1)
        .max(signalReportBulkStateRequestApiSnoozeForMax)
        .optional()
        .describe(
            "Optional, only honored when state is 'potential'. Number of additional signals the report must accumulate before it is re-promoted into the pipeline — effectively snoozing it until then. Omit to let the report re-enter the pipeline on the next matching signal."
        ),
    ids: zod
        .array(zod.uuid())
        .max(signalReportBulkStateRequestApiIdsMax)
        .describe(
            'Report ids to transition to `state` in one call (1–100). Duplicates are de-duplicated; each id is processed independently so one disallowed transition does not block the rest. `dismissal_reason`, `dismissal_note` and `snooze_for` apply to every id.'
        ),
})

export type SignalReportBulkStateRequestApi = zod.input<typeof SignalReportBulkStateRequestApi>
export type SignalReportBulkStateRequestApiOutput = zod.output<typeof SignalReportBulkStateRequestApi>

export const SignalReportBulkStateResultApi = zod.object({
    id: zod.uuid().describe('The report id this result refers to.'),
    outcome: zod
        .string()
        .describe(
            "One of: transitioned, skipped, failed, not_found. transitioned: the state change was applied. skipped: the transition was not allowed from the report's current status (a 409 on the single-report endpoint). failed: the request data was invalid for this report. not_found: no report with this id is visible to you."
        ),
    status: zod
        .string()
        .nullish()
        .describe("The report's status after the transition. Present only when outcome is 'transitioned'."),
    detail: zod
        .string()
        .nullish()
        .describe('Human-readable explanation for non-transitioned outcomes (skipped \/ failed \/ not_found).'),
})

export type SignalReportBulkStateResultApi = zod.input<typeof SignalReportBulkStateResultApi>
export type SignalReportBulkStateResultApiOutput = zod.output<typeof SignalReportBulkStateResultApi>

export const SignalReportBulkStateResponseApi = zod.object({
    results: zod
        .array(SignalReportBulkStateResultApi)
        .describe('One result per requested id, in request order (after de-duplication).'),
    transitioned_count: zod.number().describe('Number of reports whose state was changed.'),
    skipped_count: zod.number().describe('Number of reports whose transition was not allowed.'),
    failed_count: zod.number().describe('Number of reports that failed on invalid request data.'),
    not_found_count: zod.number().describe('Number of requested ids not visible to the caller.'),
})

export type SignalReportBulkStateResponseApi = zod.input<typeof SignalReportBulkStateResponseApi>
export type SignalReportBulkStateResponseApiOutput = zod.output<typeof SignalReportBulkStateResponseApi>

export const SignalReportRefundSummaryResponseApi = zod.object({
    credited_refund_count: zod
        .number()
        .describe(
            'Number of credited-path refunds across the whole organization whose refunded PR run falls in the current billing period. Excluded-path refunds never reach billing usage, so they are deliberately absent.'
        ),
    credited_credits: zod
        .number()
        .describe(
            'Total signals credits those refunds returned (1 credit = $0.01). Divide by the flat per-PR charge to get the number of PRs to subtract from billing usage.'
        ),
    period_billable_credits: zod
        .number()
        .describe(
            "The organization's live billable signals credits for the current billing period, computed by the same rules as the nightly usage report — including PRs created today that billing hasn't recorded yet, and already excluding refund-excluded and billing-exempt reports. Take the max of this and billing's recorded usage for a live PR count that reacts to new PRs and same-day refunds immediately."
        ),
})

export type SignalReportRefundSummaryResponseApi = zod.input<typeof SignalReportRefundSummaryResponseApi>
export type SignalReportRefundSummaryResponseApiOutput = zod.output<typeof SignalReportRefundSummaryResponseApi>

export const lLMSkillFileInputApiPathMax = 500

export const lLMSkillFileInputApiContentTypeDefault = `text/plain`
export const lLMSkillFileInputApiContentTypeMax = 100

export const LLMSkillFileInputApi = zod.object({
    path: zod
        .string()
        .max(lLMSkillFileInputApiPathMax)
        .describe("File path relative to skill root, e.g. 'scripts\/setup.sh' or 'references\/guide.md'."),
    content: zod.string().describe('Text content of the file.'),
    content_type: zod
        .string()
        .max(lLMSkillFileInputApiContentTypeMax)
        .default(lLMSkillFileInputApiContentTypeDefault)
        .describe('MIME type of the file content.'),
})

export type LLMSkillFileInputApi = zod.input<typeof LLMSkillFileInputApi>
export type LLMSkillFileInputApiOutput = zod.output<typeof LLMSkillFileInputApi>

export const signalScoutSlackDestinationApiChannelMax = 255

export const SignalScoutSlackDestinationApi = zod.object({
    integration_id: zod
        .number()
        .min(1)
        .describe("ID of the Slack integration whose bot posts this scout's findings and reports."),
    channel: zod
        .string()
        .max(signalScoutSlackDestinationApiChannelMax)
        .nullish()
        .describe(
            "Slack channel target in the channel picker's `channel_id|#channel-name` format. Null while choosing a channel; no messages are sent until it is set."
        ),
})

export type SignalScoutSlackDestinationApi = zod.input<typeof SignalScoutSlackDestinationApi>
export type SignalScoutSlackDestinationApiOutput = zod.output<typeof SignalScoutSlackDestinationApi>

export const SignalScoutOutputDestinationsApi = zod.object({
    slack: zod
        .union([SignalScoutSlackDestinationApi, zod.null()])
        .optional()
        .describe(
            'Slack destination for each emitted scout finding or report. Null or omitted disables Slack delivery.'
        ),
})

export type SignalScoutOutputDestinationsApi = zod.input<typeof SignalScoutOutputDestinationsApi>
export type SignalScoutOutputDestinationsApiOutput = zod.output<typeof SignalScoutOutputDestinationsApi>

export const signalScoutConfigOptionsApiRunIntervalMinutesMin = 30
export const signalScoutConfigOptionsApiRunIntervalMinutesMax = 43200

export const signalScoutConfigOptionsApiRunCronScheduleMax = 100

export const SignalScoutConfigOptionsApi = zod
    .object({
        enabled: zod.boolean().optional().describe('Whether this scout runs on its schedule. Defaults to true.'),
        emit: zod
            .boolean()
            .optional()
            .describe(
                'Whether the scout writes findings to the inbox. False = dry-run: it runs and logs but emits nothing. Defaults to true.'
            ),
        run_interval_minutes: zod
            .number()
            .min(signalScoutConfigOptionsApiRunIntervalMinutesMin)
            .max(signalScoutConfigOptionsApiRunIntervalMinutesMax)
            .optional()
            .describe('Minutes between runs (30–43200). Defaults to 1440 (every 24 hours).'),
        output_destinations: SignalScoutOutputDestinationsApi.optional().describe(
            'Destinations that receive each finding or report this scout emits. Empty by default.'
        ),
        auto_pause_exempt: zod
            .boolean()
            .optional()
            .describe(
                'Exempt this scout from the inactivity pause, which otherwise switches off a scout that goes a fortnight without surfacing anything anyone engages with. Set it on watchdog scouts whose value is staying quiet. Defaults to false.'
            ),
        run_cron_schedule: zod
            .string()
            .max(signalScoutConfigOptionsApiRunCronScheduleMax)
            .nullish()
            .describe(
                "Optional five-field cron expression, e.g. '30 9 \* \* \*' (daily at 09:30), '0 9,17 \* \* \*' (twice daily), or '0 9 \* \* 1-5' (weekday mornings). Evaluated in the project timezone. Takes precedence over `run_interval_minutes`; occurrences must be at least 30 minutes apart."
            ),
    })
    .describe('Schedule, enablement, and delivery options accepted while creating a scout.')

export type SignalScoutConfigOptionsApi = zod.input<typeof SignalScoutConfigOptionsApi>
export type SignalScoutConfigOptionsApiOutput = zod.output<typeof SignalScoutConfigOptionsApi>

export const signalScoutCreateApiNameMax = 64

export const signalScoutCreateApiDescriptionMax = 4096

export const SignalScoutCreateApi = zod
    .object({
        name: zod
            .string()
            .max(signalScoutCreateApiNameMax)
            .describe(
                'Unique scout name. Must start with `signals-scout-` and contain only lowercase letters, numbers, and hyphens.'
            ),
        description: zod
            .string()
            .max(signalScoutCreateApiDescriptionMax)
            .describe('Short description of the signal or behavior this scout investigates.'),
        body: zod
            .string()
            .describe(
                'Complete markdown prompt executed on every scout run. Include any project-specific signal names, thresholds, investigation steps, and report criteria here.'
            ),
        files: zod
            .array(LLMSkillFileInputApi)
            .optional()
            .describe('Optional reference files bundled with the scout prompt.'),
        config: SignalScoutConfigOptionsApi.optional().describe(
            'Optional schedule, enablement, dry-run posture, and delivery settings. Defaults to an enabled, emitting scout on the daily interval with no external destination.'
        ),
    })
    .describe('Create a runnable custom scout and its config in one atomic request.')

export type SignalScoutCreateApi = zod.input<typeof SignalScoutCreateApi>
export type SignalScoutCreateApiOutput = zod.output<typeof SignalScoutCreateApi>

export const SignalScoutSkillSummaryApi = zod.object({
    id: zod.uuid(),
    name: zod.string(),
    description: zod.string(),
    version: zod.number(),
    allowed_tools: zod.array(zod.string()).describe('Server-managed report tools granted to this scout.'),
})

export type SignalScoutSkillSummaryApi = zod.input<typeof SignalScoutSkillSummaryApi>
export type SignalScoutSkillSummaryApiOutput = zod.output<typeof SignalScoutSkillSummaryApi>

export const ScoutOriginEnumApi = zod.enum(['canonical', 'custom'])

export type ScoutOriginEnumApi = zod.input<typeof ScoutOriginEnumApi>
export type ScoutOriginEnumApiOutput = zod.output<typeof ScoutOriginEnumApi>

export const ScoutConfigStatusEnumApi = zod
    .enum(['active', 'pending_pause', 'paused_by_system', 'paused_by_user'])
    .describe(
        '\* `active` - Active\n\* `pending_pause` - Pending pause\n\* `paused_by_system` - Paused by system\n\* `paused_by_user` - Paused by user'
    )

export type ScoutConfigStatusEnumApi = zod.input<typeof ScoutConfigStatusEnumApi>
export type ScoutConfigStatusEnumApiOutput = zod.output<typeof ScoutConfigStatusEnumApi>

export const ScoutConfigPauseReasonEnumApi = zod
    .enum(['no_output', 'ignored', 'repeated_failures'])
    .describe('\* `no_output` - No output\n\* `ignored` - Ignored\n\* `repeated_failures` - Repeated failures')

export type ScoutConfigPauseReasonEnumApi = zod.input<typeof ScoutConfigPauseReasonEnumApi>
export type ScoutConfigPauseReasonEnumApiOutput = zod.output<typeof ScoutConfigPauseReasonEnumApi>

export const signalScoutConfigApiRunIntervalMinutesMin = 30
export const signalScoutConfigApiRunIntervalMinutesMax = 43200

export const SignalScoutConfigApi = zod
    .object({
        id: zod.uuid(),
        skill_name: zod
            .string()
            .describe('The `signals-scout-\*` skill this config controls. Set at creation, not editable.'),
        description: zod
            .string()
            .describe(
                "Human-readable summary of what this scout investigates, sourced from the scout skill's `description` metadata. Use it for a quick steer on the scout's focus without loading the full skill body. Empty if the skill is not currently present on the team or carries no description."
            ),
        scout_origin: ScoutOriginEnumApi.describe(
            'Where this scout came from: `canonical` for a scout PostHog ships and maintains (seeded from `products\/signals\/skills\/`), or `custom` for one a team hand-authored on this project. Use it to badge built-in vs custom scouts instead of a hardcoded name list. Defaults to `custom` if the skill is not currently present on the team.'
        ),
        enabled: zod
            .boolean()
            .describe(
                'Whether this scout runs on its schedule. Disabled scouts are skipped by the coordinator. Derived from `status`: true for `active` and `pending_pause`, false for the paused statuses.'
            ),
        status: ScoutConfigStatusEnumApi.describe(
            'Lifecycle status. `active`: runs on its schedule. `pending_pause`: still running, but flagged by the system to pause soon unless something changes (any config edit clears it). `paused_by_system`: paused automatically, see `pause_reason`; set `enabled=true` to resume. `paused_by_user`: switched off by a person and never resumed automatically.\n\n\* `active` - Active\n\* `pending_pause` - Pending pause\n\* `paused_by_system` - Paused by system\n\* `paused_by_user` - Paused by user'
        ),
        pause_reason: zod
            .union([ScoutConfigPauseReasonEnumApi, zod.null()])
            .describe(
                'Why the system paused (or warned) this scout: `no_output` (it emitted nothing over the evaluation window), `ignored` (its output received no human engagement), or `repeated_failures` (consecutive failed runs). Null unless `status` is `pending_pause` or `paused_by_system`.\n\n\* `no_output` - No output\n\* `ignored` - Ignored\n\* `repeated_failures` - Repeated failures'
            ),
        emit: zod
            .boolean()
            .describe(
                'Whether the scout writes findings to the inbox. False = dry-run: it runs and logs but emits nothing.'
            ),
        run_interval_minutes: zod
            .number()
            .min(signalScoutConfigApiRunIntervalMinutesMin)
            .max(signalScoutConfigApiRunIntervalMinutesMax)
            .describe(
                'Minutes between runs (30–43200). The scout runs once this interval has elapsed since its last run.'
            ),
        run_cron_schedule: zod
            .string()
            .nullable()
            .describe(
                "Optional five-field cron expression evaluated in the project timezone, e.g. '30 9 \* \* \*'. Takes precedence over `run_interval_minutes` when set. Null means the rolling interval schedule."
            ),
        output_destinations: SignalScoutOutputDestinationsApi.describe(
            'Destinations that receive each finding or report this scout emits. Empty when none is configured.'
        ),
        last_run_at: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe('When the coordinator last dispatched this scout. Null if it has never run.'),
        consecutive_failure_count: zod
            .number()
            .describe(
                "How many of this scout's runs have failed in a row. Back to 0 after a successful run or any config edit. At the failure limit the scout pauses itself (`status` becomes `paused_by_system` with `pause_reason` `repeated_failures`) and retries about once a day; a successful retry resumes it, and so does setting `enabled=true`."
            ),
        status_changed_at: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe(
                'When `status` last changed. For `pending_pause` this is when the warning was issued (the pause lands about a week later unless the scout surfaces something); for the paused statuses it is when the scout was paused. Null if the status never changed.'
            ),
        auto_pause_exempt: zod
            .boolean()
            .describe(
                'Whether this scout is exempt from the inactivity pause. Set it on watchdog scouts whose value is staying quiet, so silence is never read as waste. Also set automatically when someone re-enables a scout the inactivity sweep paused, so the sweep never overrules a person twice.'
            ),
        created_at: zod.iso.datetime({ offset: true }),
    })
    .describe(
        'Read shape for a per-(team, skill) scout config.\n\nOne row per `signals-scout-\*` skill on the team. The coordinator auto-creates a row\nwhen it discovers a scout skill; this serializer lets agents tune the row.'
    )

export type SignalScoutConfigApi = zod.input<typeof SignalScoutConfigApi>
export type SignalScoutConfigApiOutput = zod.output<typeof SignalScoutConfigApi>

export const SignalScoutCreateResponseApi = zod.object({
    created: zod
        .boolean()
        .describe('True when this request created the missing scout skill or config; false when both already existed.'),
    skill: SignalScoutSkillSummaryApi,
    config: SignalScoutConfigApi,
})

export type SignalScoutCreateResponseApi = zod.input<typeof SignalScoutCreateResponseApi>
export type SignalScoutCreateResponseApiOutput = zod.output<typeof SignalScoutCreateResponseApi>

export const signalScoutConfigCreateApiRunIntervalMinutesMin = 30
export const signalScoutConfigCreateApiRunIntervalMinutesMax = 43200

export const signalScoutConfigCreateApiRunCronScheduleMax = 100

export const signalScoutConfigCreateApiSkillNameMax = 200

export const SignalScoutConfigCreateApi = zod
    .object({
        enabled: zod.boolean().optional().describe('Whether this scout runs on its schedule. Defaults to true.'),
        emit: zod
            .boolean()
            .optional()
            .describe(
                'Whether the scout writes findings to the inbox. False = dry-run: it runs and logs but emits nothing. Defaults to true.'
            ),
        run_interval_minutes: zod
            .number()
            .min(signalScoutConfigCreateApiRunIntervalMinutesMin)
            .max(signalScoutConfigCreateApiRunIntervalMinutesMax)
            .optional()
            .describe('Minutes between runs (30–43200). Defaults to 1440 (every 24 hours).'),
        output_destinations: SignalScoutOutputDestinationsApi.optional().describe(
            'Destinations that receive each finding or report this scout emits. Empty by default.'
        ),
        auto_pause_exempt: zod
            .boolean()
            .optional()
            .describe(
                'Exempt this scout from the inactivity pause, which otherwise switches off a scout that goes a fortnight without surfacing anything anyone engages with. Set it on watchdog scouts whose value is staying quiet. Defaults to false.'
            ),
        run_cron_schedule: zod
            .string()
            .max(signalScoutConfigCreateApiRunCronScheduleMax)
            .nullish()
            .describe(
                "Optional five-field cron expression, e.g. '30 9 \* \* \*' (daily at 09:30), '0 9,17 \* \* \*' (twice daily), or '0 9 \* \* 1-5' (weekday mornings). Evaluated in the project timezone. Takes precedence over `run_interval_minutes`; occurrences must be at least 30 minutes apart."
            ),
        skill_name: zod
            .string()
            .max(signalScoutConfigCreateApiSkillNameMax)
            .describe(
                'The `signals-scout-\*` skill to register a config for. The skill must already exist on this project — author it via the skills store first.'
            ),
    })
    .describe(
        'Request body for registering a scout config without waiting for the coordinator tick.\n\nUpsert keyed on `skill_name`: if the coordinator (or a concurrent caller) already\nregistered the row, the provided tunables are applied to it instead.'
    )

export type SignalScoutConfigCreateApi = zod.input<typeof SignalScoutConfigCreateApi>
export type SignalScoutConfigCreateApiOutput = zod.output<typeof SignalScoutConfigCreateApi>

export const patchedSignalScoutConfigUpdateApiRunIntervalMinutesMin = 30
export const patchedSignalScoutConfigUpdateApiRunIntervalMinutesMax = 43200

export const patchedSignalScoutConfigUpdateApiRunCronScheduleMax = 100

export const PatchedSignalScoutConfigUpdateApi = zod
    .object({
        enabled: zod
            .boolean()
            .optional()
            .describe(
                'Whether this scout runs on its schedule. Disabled scouts are skipped by the coordinator. Turning this off records a user pause (`status` becomes `paused_by_user`, which the system never overrides); turning it on resumes the scout from any pause. Only a change of value is a lifecycle action: re-sending the current value leaves the existing status and its ownership untouched.'
            ),
        emit: zod
            .boolean()
            .optional()
            .describe(
                'Whether the scout writes findings to the inbox. False = dry-run: it runs and logs but emits nothing.'
            ),
        run_interval_minutes: zod
            .number()
            .min(patchedSignalScoutConfigUpdateApiRunIntervalMinutesMin)
            .max(patchedSignalScoutConfigUpdateApiRunIntervalMinutesMax)
            .optional()
            .describe('Minutes between runs (30–43200). Use 1440 for a daily schedule.'),
        run_cron_schedule: zod
            .string()
            .max(patchedSignalScoutConfigUpdateApiRunCronScheduleMax)
            .nullish()
            .describe(
                "Optional five-field cron expression, e.g. '30 9 \* \* \*' (daily at 09:30), '0 9,17 \* \* \*' (twice daily), or '0 9 \* \* 1-5' (weekday mornings). Evaluated in the project timezone. Takes precedence over `run_interval_minutes`; occurrences must be at least 30 minutes apart. Set null to return to the rolling interval schedule."
            ),
        output_destinations: SignalScoutOutputDestinationsApi.optional().describe(
            'Destinations that receive each finding or report this scout emits. Pass an empty object to disable delivery.'
        ),
        auto_pause_exempt: zod
            .boolean()
            .optional()
            .describe(
                'Exempt this scout from the inactivity pause. Set it on watchdog scouts whose value is staying quiet, so silence is never read as waste.'
            ),
    })
    .describe('Editable schedule, enablement, and emit posture for one scout config.')

export type PatchedSignalScoutConfigUpdateApi = zod.input<typeof PatchedSignalScoutConfigUpdateApi>
export type PatchedSignalScoutConfigUpdateApiOutput = zod.output<typeof PatchedSignalScoutConfigUpdateApi>

export const SignalScoutManualRunApi = zod
    .object({
        skill_name: zod.string().describe('The `signals-scout-\*` skill that was dispatched.'),
        workflow_id: zod
            .string()
            .describe(
                "Temporal workflow id for the dispatched run. The run executes asynchronously; poll the scout's runs to see the resulting run row, its status, and any emitted findings."
            ),
        started: zod
            .boolean()
            .describe(
                'True when a new run was dispatched. The endpoint returns 409 instead when a run for this scout is already in progress.'
            ),
    })
    .describe(
        "Response for an on-demand (`run now`) scout dispatch.\n\nThe run executes asynchronously on the Temporal worker, so there is no `SignalScoutRun`\nrow yet at response time — the bridge row is created once the run's first turn starts.\nPoll the scout's runs (`scout-runs-list`) to see the resulting run and its findings."
    )

export type SignalScoutManualRunApi = zod.input<typeof SignalScoutManualRunApi>
export type SignalScoutManualRunApiOutput = zod.output<typeof SignalScoutManualRunApi>

export const ScoutMemberApi = zod
    .object({
        user_uuid: zod
            .string()
            .describe(
                "The member's stable PostHog user UUID — the same id that appears as `created_by.uuid` on entities they own. A durable handle for this person across runs."
            ),
        email: zod.email().describe("The member's email — use to match a finding's owner by name\/email."),
        first_name: zod.string().describe("The member's first name (may be empty)."),
        last_name: zod.string().describe("The member's last name (may be empty)."),
        github_login: zod
            .string()
            .nullable()
            .describe(
                "The member's resolved GitHub login (lowercased), already resolved server-side — put this value in a report's `suggested_reviewers` once you've matched the finding's owner to this row. Null when the member has no linked GitHub identity: a null-login member can't be routed to at all (neither a login nor a uuid resolves), so pick a different owner or leave `suggested_reviewers` empty."
            ),
    })
    .describe("One project member's routing identity, for picking a `suggested_reviewers` entry on a report.")

export type ScoutMemberApi = zod.input<typeof ScoutMemberApi>
export type ScoutMemberApiOutput = zod.output<typeof ScoutMemberApi>

export const ScoutLimitsApi = zod
    .object({
        max_runs_per_tick: zod
            .number()
            .describe('Most scout runs the team can start in a single 30-minute coordinator tick.'),
        max_runs_per_day: zod
            .number()
            .nullable()
            .describe('Most scout runs the team can start per rolling 24 hours, or null when uncapped.'),
        runs_today: zod.number().describe('Scout runs the team has started in the trailing 24 hours.'),
        runs_remaining_today: zod
            .number()
            .nullable()
            .describe(
                'Runs still allowed in the trailing 24h window (max_runs_per_day − runs_today), or null when uncapped.'
            ),
    })
    .describe(
        "A team's enforced scout run caps and current usage.\n\nThese are the values the coordinator actually applies at dispatch (resolved per-team override →\nfleet-wide default → code constant), so the UI can show the real throttle rather than what a\nuser thinks they configured."
    )

export type ScoutLimitsApi = zod.input<typeof ScoutLimitsApi>
export type ScoutLimitsApiOutput = zod.output<typeof ScoutLimitsApi>

export const ScoutMetadataApi = zod
    .object({
        enrolled: zod
            .boolean()
            .describe(
                'Whether this project runs scouts. True when the project is in the signals-scout flag\'s enrollment set — either listed explicitly in guaranteed_team_ids or covered by the \"\*\" wildcard (every project that turns scouts on) — and not in skip_team_ids.'
            ),
        banner_message: zod
            .string()
            .nullable()
            .describe(
                'Free-form announcement banner to show above the scout UI (e.g. alpha run-limit notice), or null when unset.'
            ),
        limits: ScoutLimitsApi.describe("The team's enforced scout run caps and current usage."),
    })
    .describe(
        'Team-scoped scout metadata for the inbox \/ Code-app UIs: enrollment, the alpha banner, and\nthe enforced limits. Sourced from the `signals-scout` flag payload so the banner and caps can\nchange without a deploy to either app.'
    )

export type ScoutMetadataApi = zod.input<typeof ScoutMetadataApi>
export type ScoutMetadataApiOutput = zod.output<typeof ScoutMetadataApi>

export const ScoutNoteApi = zod
    .object({
        id: zod.string().describe('Note UUID. Pass to `scout-notes-delete` to retire the note.'),
        skill_name: zod
            .string()
            .describe(
                'Target scout skill (`signals-scout-\*`), or blank for a general note addressed to every scout on the fleet.'
            ),
        content: zod.string().describe("The note's prose, read verbatim by scout runs."),
        created_at: zod.string().nullable().describe('ISO-8601 creation timestamp.'),
        expires_at: zod
            .string()
            .nullable()
            .describe('ISO-8601 expiry, or null for a note that stays active until deleted.'),
        created_by_name: zod
            .string()
            .nullable()
            .describe('Display name of the user who left the note, or null when unavailable.'),
        origin: zod
            .string()
            .describe(
                "Where the note came from. `human` for one left directly through this API. `report_dismissal` for one forwarded from the note someone typed when they dismissed, snoozed, or restored one or more inbox reports: one reviewer's verdict on the reports its content names, so weigh it as evidence about those reports rather than as fleet-level steering. `report_discussion` for the question someone asked when they opened a discussion on a report: context to weigh, neither a verdict on the report nor a directive."
            ),
    })
    .describe('`SignalScoutNote` projection used by `notes-list` and `notes-create`.')

export type ScoutNoteApi = zod.input<typeof ScoutNoteApi>
export type ScoutNoteApiOutput = zod.output<typeof ScoutNoteApi>

export const scoutNoteCreateRequestApiContentMax = 10000

export const scoutNoteCreateRequestApiSkillNameMax = 200

export const ScoutNoteCreateRequestApi = zod
    .object({
        content: zod
            .string()
            .max(scoutNoteCreateRequestApiContentMax)
            .describe(
                "The note's prose — feedback, a pointer, or a nudge for the scout(s) to weigh on their next runs (e.g. 'we shipped a new checkout on Tuesday, watch conversion closely', 'stop flagging the staging traffic spike'). Write it in Markdown; scouts read it verbatim."
            ),
        skill_name: zod
            .string()
            .max(scoutNoteCreateRequestApiSkillNameMax)
            .optional()
            .describe(
                'Address the note to one scout by its skill name (`signals-scout-\*`, exact match against an existing scout skill on the project — check `scout-config-list` for the roster). Omit or leave blank for a general note every scout sees.'
            ),
        expires_at: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe(
                "Optional ISO-8601 expiry. After this time the note drops out of the default list view, so time-boxed steering ('watch closely this week') retires itself. Omit for a note that stays active until deleted."
            ),
    })
    .describe('Request body for `notes-create`.')

export type ScoutNoteCreateRequestApi = zod.input<typeof ScoutNoteCreateRequestApi>
export type ScoutNoteCreateRequestApiOutput = zod.output<typeof ScoutNoteCreateRequestApi>

export const ProjectContextApi = zod
    .object({
        product_description: zod
            .string()
            .nullable()
            .describe(
                'Human-set product description on the project (max 1000 chars). When present, the most direct \"what does this team\'s product do\" answer. `null` when unset.'
            ),
        app_urls: zod
            .array(zod.string())
            .describe(
                "Registered app URLs for this team (toolbar \/ replay). The team's actual product surface; complements `$pageview.$host` discovery via `read-data-schema`."
            ),
    })
    .describe("`inventory.project_context` — free-form orientation about the project's product.")

export type ProjectContextApi = zod.input<typeof ProjectContextApi>
export type ProjectContextApiOutput = zod.output<typeof ProjectContextApi>

export const ProductIntentEntryApi = zod
    .object({
        product_type: zod.string().describe('Product key the team signaled intent to use.'),
        activated_at: zod
            .string()
            .nullable()
            .describe('ISO-8601 timestamp the team activated the product, or null if intent only.'),
        created_at: zod.string().nullable().describe('ISO-8601 timestamp the intent was first recorded.'),
    })
    .describe('One row in `inventory.product_intents`.')

export type ProductIntentEntryApi = zod.input<typeof ProductIntentEntryApi>
export type ProductIntentEntryApiOutput = zod.output<typeof ProductIntentEntryApi>

export const IntegrationEntryApi = zod
    .object({
        kind: zod.string().describe('Integration kind (e.g. `slack`, `github`, `linear`).'),
        created_at: zod.string().nullable().describe('ISO-8601 timestamp the integration was connected.'),
    })
    .describe('One row in `inventory.integrations`. Sensitive config is intentionally excluded.')

export type IntegrationEntryApi = zod.input<typeof IntegrationEntryApi>
export type IntegrationEntryApiOutput = zod.output<typeof IntegrationEntryApi>

export const ExternalDataSourceEntryApi = zod
    .object({
        source_type: zod.string().describe('Warehouse source type (e.g. `Stripe`, `Postgres`, `BigQuery`).'),
        status: zod.string().describe('Current sync status (`Running`, `Failed`, `Paused`, etc.).'),
        prefix: zod.string().describe('Schema prefix used by this source, if any.'),
        created_at: zod.string().nullable().describe('ISO-8601 timestamp the source was connected.'),
        last_run_at: zod
            .string()
            .nullable()
            .describe(
                'ISO-8601 timestamp of the most recent completed sync job, or null if this source has never completed a sync. Use this to tell a healthy source apart from one stuck in `Running` that has imported zero rows — `status` alone conflates the two.'
            ),
        latest_error: zod
            .string()
            .nullable()
            .describe('Newest schema-level sync error for this source, or null if no schema is erroring.'),
    })
    .describe('One row in `inventory.external_data_sources`.')

export type ExternalDataSourceEntryApi = zod.input<typeof ExternalDataSourceEntryApi>
export type ExternalDataSourceEntryApiOutput = zod.output<typeof ExternalDataSourceEntryApi>

export const SignalSourceConfigEntryApi = zod
    .object({
        source_product: zod.string().describe('Source product the config applies to.'),
        source_type: zod.string().describe('Source type within the product.'),
    })
    .describe('One row in either bucket of `inventory.signal_source_configs`.')

export type SignalSourceConfigEntryApi = zod.input<typeof SignalSourceConfigEntryApi>
export type SignalSourceConfigEntryApiOutput = zod.output<typeof SignalSourceConfigEntryApi>

export const SignalSourceConfigsBucketsApi = zod
    .object({
        enabled: zod.array(SignalSourceConfigEntryApi).describe('Source configs the team has explicitly enabled.'),
        disabled: zod
            .array(SignalSourceConfigEntryApi)
            .describe('Source configs the team has explicitly disabled (different from never wired up).'),
    })
    .describe('`inventory.signal_source_configs` split into enabled and disabled buckets.')

export type SignalSourceConfigsBucketsApi = zod.input<typeof SignalSourceConfigsBucketsApi>
export type SignalSourceConfigsBucketsApiOutput = zod.output<typeof SignalSourceConfigsBucketsApi>

export const EmitEligibilityApi = zod
    .object({
        ai_processing_approved: zod
            .boolean()
            .describe(
                'Whether the organization has approved AI data processing (an org-level gate on all scout emits).'
            ),
        source_enabled: zod.boolean().describe('Whether the `signals_scout` signal source is enabled for this team.'),
        can_emit: zod
            .boolean()
            .describe(
                "True only when both team\/org-level gates pass, so scout findings (signal and report channels alike) actually reach the inbox. When False, every emit is silently dropped — quick-close instead of doing throwaway investigation. Does not account for a scout's own dry-run `emit` toggle, which is per-config, not team-wide."
            ),
        remediation: zod
            .string()
            .nullable()
            .describe('One-line next step to unblock emits when `can_emit` is False; null when emits can flow.'),
    })
    .describe('`inventory.emit_eligibility` — whether scout findings can reach the inbox for this team.')

export type EmitEligibilityApi = zod.input<typeof EmitEligibilityApi>
export type EmitEligibilityApiOutput = zod.output<typeof EmitEligibilityApi>

export const ScoutFleetEntryApi = zod
    .object({
        skill_name: zod.string().describe('The `signals-scout-\*` skill this config schedules.'),
        run_interval_minutes: zod
            .number()
            .describe('Minutes between runs when no cron schedule is set (default 1440, every 24 hours).'),
        run_cron_schedule: zod
            .string()
            .nullable()
            .describe(
                'Optional cron expression, evaluated in the project timezone. Takes precedence over the interval.'
            ),
        emit: zod
            .boolean()
            .describe(
                "Whether this scout's findings actually reach the inbox. False means dry-run: it runs and logs but emits nothing, so its silence says nothing about the surface it watches."
            ),
        last_run_at: zod
            .string()
            .nullable()
            .describe('ISO-8601 timestamp the coordinator last dispatched this scout, or null if it has never run.'),
        last_emitted_at: zod
            .string()
            .nullable()
            .describe(
                'ISO-8601 timestamp this scout last produced output on either channel (a finding, or an authored\/edited report), within `emitted_lookback_days`. Null means quiet for at least that window, not never.'
            ),
        not_running_reason: zod
            .string()
            .nullable()
            .describe(
                'Why this scout is in the `disabled` bucket: `turned_off` (a person or seed posture set it off), `auto_paused` (the system paused it), or `skill_unavailable` (left on, but its skill was deleted, superseded, or withheld, so it never dispatches). Null for scouts that actually run.'
            ),
        pause_reason: zod
            .string()
            .nullable()
            .describe(
                'The cause behind an `auto_paused` entry: `no_output`, `ignored`, or `repeated_failures`. Null for every other entry.'
            ),
    })
    .describe('One scout in either bucket of `inventory.scout_fleet`.')

export type ScoutFleetEntryApi = zod.input<typeof ScoutFleetEntryApi>
export type ScoutFleetEntryApiOutput = zod.output<typeof ScoutFleetEntryApi>

export const ScoutFleetApi = zod
    .object({
        enabled: zod
            .array(ScoutFleetEntryApi)
            .describe('Scouts that actually run on this team: enabled, with a live skill the coordinator dispatches.'),
        disabled: zod
            .array(ScoutFleetEntryApi)
            .describe(
                "Scouts that do not run, each carrying a `not_running_reason` — turned off, or left on with a skill that can't dispatch. Different from a surface no scout ever covered."
            ),
        emitted_lookback_days: zod
            .number()
            .describe("The window `last_emitted_at` was resolved over, so a null reads as 'quiet', not 'never'."),
    })
    .describe('`inventory.scout_fleet` — the other scouts running on this project, split by enablement.')

export type ScoutFleetApi = zod.input<typeof ScoutFleetApi>
export type ScoutFleetApiOutput = zod.output<typeof ScoutFleetApi>

export const InboxReportStatusBucketApi = zod
    .object({
        status: zod.string().describe('Report status (e.g. `potential`, `candidate`, `ready`).'),
        count: zod.number().describe('Number of reports in this status (excludes deleted\/suppressed).'),
    })
    .describe('One bucket in `inventory.existing_inbox_reports.by_status`.')

export type InboxReportStatusBucketApi = zod.input<typeof InboxReportStatusBucketApi>
export type InboxReportStatusBucketApiOutput = zod.output<typeof InboxReportStatusBucketApi>

export const ExistingInboxReportsApi = zod
    .object({
        total: zod.number().describe('Total non-deleted, non-suppressed reports for this team.'),
        by_status: zod.array(InboxReportStatusBucketApi).describe('Per-status breakdown of inbox reports.'),
    })
    .describe("`inventory.existing_inbox_reports` — what's already been surfaced to the inbox.")

export type ExistingInboxReportsApi = zod.input<typeof ExistingInboxReportsApi>
export type ExistingInboxReportsApiOutput = zod.output<typeof ExistingInboxReportsApi>

export const ScopeActivityEntryApi = zod
    .object({
        scope: zod.string().describe('Activity-log scope (entity type), e.g. `FeatureFlag`, `Dashboard`, `Survey`.'),
        edits: zod.number().describe('Total activity-log entries for this scope in the window (write velocity).'),
        users: zod.number().describe('Distinct users who edited this scope in the window.'),
        last_edit: zod.string().nullable().describe('ISO-8601 timestamp of the most recent edit in the window.'),
    })
    .describe('One row in `inventory.recent_activity.by_scope`.')

export type ScopeActivityEntryApi = zod.input<typeof ScopeActivityEntryApi>
export type ScopeActivityEntryApiOutput = zod.output<typeof ScopeActivityEntryApi>

export const RecentActivityApi = zod
    .object({
        window_days: zod.number().describe('Lookback window in days the per-scope counts cover.'),
        by_scope: zod
            .array(ScopeActivityEntryApi)
            .describe(
                'Per-scope activity rows, busiest scope first. Triage which entity type the team has worked in lately.'
            ),
    })
    .describe('`inventory.recent_activity` — per-scope counts off the activity log.')

export type RecentActivityApi = zod.input<typeof RecentActivityApi>
export type RecentActivityApiOutput = zod.output<typeof RecentActivityApi>

export const ReviewerCorrectionEntryApi = zod
    .object({
        report_id: zod.string().describe('UUID of the report whose reviewers a human edited.'),
        report_title: zod.string().nullable().describe('Report title at the time of the edit.'),
        before: zod.array(zod.string()).describe('GitHub logins on the report before the human edit (lowercased).'),
        after: zod.array(zod.string()).describe('GitHub logins on the report after the human edit (lowercased).'),
        at: zod.string().nullable().describe('ISO-8601 timestamp of the edit.'),
    })
    .describe('One row in `inventory.recent_reviewer_corrections.corrections`.')

export type ReviewerCorrectionEntryApi = zod.input<typeof ReviewerCorrectionEntryApi>
export type ReviewerCorrectionEntryApiOutput = zod.output<typeof ReviewerCorrectionEntryApi>

export const RecentReviewerCorrectionsApi = zod
    .object({
        window_days: zod.number().describe('Lookback window in days the corrections cover.'),
        corrections: zod
            .array(ReviewerCorrectionEntryApi)
            .describe(
                "Human reviewer edits, newest first. A human swapping a report's suggested reviewers is authoritative ownership precedent — route to who they chose."
            ),
    })
    .describe('`inventory.recent_reviewer_corrections` — human edits to report reviewer lists.')

export type RecentReviewerCorrectionsApi = zod.input<typeof RecentReviewerCorrectionsApi>
export type RecentReviewerCorrectionsApiOutput = zod.output<typeof RecentReviewerCorrectionsApi>

export const RecentDashboardEntryApi = zod
    .object({
        id: zod.number().describe('Dashboard ID — pass to `dashboard-get` to pull the full payload.'),
        name: zod.string().describe('Dashboard name (may be blank if unnamed).'),
        last_accessed_at: zod
            .string()
            .nullable()
            .describe('ISO-8601 timestamp of the most recent view in the PostHog UI.'),
        last_refresh: zod
            .string()
            .nullable()
            .describe(
                'ISO-8601 timestamp of the most recent data refresh. Distinct from access — a dashboard can be refreshed without anyone viewing it.'
            ),
        created_at: zod.string().nullable().describe('ISO-8601 timestamp the dashboard was created.'),
    })
    .describe('One row in `inventory.recent_dashboards`.')

export type RecentDashboardEntryApi = zod.input<typeof RecentDashboardEntryApi>
export type RecentDashboardEntryApiOutput = zod.output<typeof RecentDashboardEntryApi>

export const RecentSurveyEntryApi = zod
    .object({
        id: zod.string().describe('Survey UUID — pass to `survey-get` for full question shape.'),
        name: zod.string().describe('Survey name (may be blank if unnamed).'),
        type: zod.string().describe('Survey mode: `popover`, `widget`, `external_survey`, or `api`.'),
        status: zod.string().describe('Derived status: `draft`, `running`, `stopped`, or `archived`.'),
        updated_at: zod.string().nullable().describe('ISO-8601 last-modified timestamp.'),
    })
    .describe('One row in `inventory.recent_surveys.recent`.')

export type RecentSurveyEntryApi = zod.input<typeof RecentSurveyEntryApi>
export type RecentSurveyEntryApiOutput = zod.output<typeof RecentSurveyEntryApi>

export const RecentSurveysApi = zod
    .object({
        total_count: zod.number().describe('Total surveys on the team.'),
        active_count: zod.number().describe('Surveys that are live (not archived, started, and not yet ended).'),
        recent: zod.array(RecentSurveyEntryApi).describe('The 5 most recently updated surveys.'),
    })
    .describe('`inventory.recent_surveys` — total + active count, plus the 5 most recently modified.')

export type RecentSurveysApi = zod.input<typeof RecentSurveysApi>
export type RecentSurveysApiOutput = zod.output<typeof RecentSurveysApi>

export const RecentFeatureFlagEntryApi = zod
    .object({
        id: zod.number().describe('Feature flag ID.'),
        key: zod.string().describe("Flag key used in code (`posthog.isFeatureEnabled('<key>')`)."),
        name: zod.string().describe('Human-set description; falls back to the key when blank.'),
        active: zod.boolean().describe('Whether the flag is currently evaluating (a user could be hitting it).'),
        updated_at: zod.string().nullable().describe('ISO-8601 last-modified timestamp.'),
    })
    .describe('One row in `inventory.recent_feature_flags.recent`.')

export type RecentFeatureFlagEntryApi = zod.input<typeof RecentFeatureFlagEntryApi>
export type RecentFeatureFlagEntryApiOutput = zod.output<typeof RecentFeatureFlagEntryApi>

export const RecentFeatureFlagsApi = zod
    .object({
        total_count: zod.number().describe('Total non-deleted feature flags on the team.'),
        active_count: zod.number().describe('Flags currently evaluating (`active=true`).'),
        recent: zod.array(RecentFeatureFlagEntryApi).describe('The 5 most recently updated non-deleted flags.'),
    })
    .describe('`inventory.recent_feature_flags` — total + active count, plus the 5 most recently modified.')

export type RecentFeatureFlagsApi = zod.input<typeof RecentFeatureFlagsApi>
export type RecentFeatureFlagsApiOutput = zod.output<typeof RecentFeatureFlagsApi>

export const RecentExperimentEntryApi = zod
    .object({
        id: zod.number().describe('Experiment ID.'),
        name: zod.string().describe('Experiment name.'),
        status: zod.string().describe('Derived status: `draft`, `running`, `stopped`, or `archived`.'),
        feature_flag_key: zod
            .string()
            .nullable()
            .describe(
                "Key of the experiment's feature flag — cross-ref into `recent_feature_flags`. Null if unlinked."
            ),
        updated_at: zod.string().nullable().describe('ISO-8601 last-modified timestamp.'),
    })
    .describe('One row in `inventory.recent_experiments.recent`.')

export type RecentExperimentEntryApi = zod.input<typeof RecentExperimentEntryApi>
export type RecentExperimentEntryApiOutput = zod.output<typeof RecentExperimentEntryApi>

export const RecentExperimentsApi = zod
    .object({
        total_count: zod.number().describe('Total experiments on the team.'),
        running_count: zod.number().describe('Experiments currently running (started, not ended, not archived).'),
        recent: zod.array(RecentExperimentEntryApi).describe('The 5 most recently updated experiments.'),
    })
    .describe('`inventory.recent_experiments` — total + currently-running count, plus the 5 most recently modified.')

export type RecentExperimentsApi = zod.input<typeof RecentExperimentsApi>
export type RecentExperimentsApiOutput = zod.output<typeof RecentExperimentsApi>

export const RecentAlertEntryApi = zod
    .object({
        id: zod.string().describe('Alert configuration UUID.'),
        name: zod.string().describe('Alert name.'),
        enabled: zod.boolean().describe('Whether the alert is currently armed.'),
        state: zod.string().describe('Alert state (e.g. `not_firing`, `firing`).'),
        calculation_interval: zod
            .string()
            .nullable()
            .describe('How often the alert is evaluated (e.g. `daily`, `hourly`); null if unset.'),
        insight_id: zod.number().nullable().describe('ID of the insight the alert watches; null if none.'),
        created_at: zod.string().nullable().describe('ISO-8601 creation timestamp.'),
    })
    .describe('One row in `inventory.recent_alerts.recent`.')

export type RecentAlertEntryApi = zod.input<typeof RecentAlertEntryApi>
export type RecentAlertEntryApiOutput = zod.output<typeof RecentAlertEntryApi>

export const RecentAlertsApi = zod
    .object({
        total_count: zod.number().describe('Total insight alerts on the team.'),
        enabled_count: zod.number().describe('Alerts currently armed (`enabled=true`).'),
        recent: zod.array(RecentAlertEntryApi).describe('The 5 most recently created alerts.'),
    })
    .describe('`inventory.recent_alerts` — total + currently-enabled count, plus the 5 most recently created.')

export type RecentAlertsApi = zod.input<typeof RecentAlertsApi>
export type RecentAlertsApiOutput = zod.output<typeof RecentAlertsApi>

export const RecentHogFunctionEntryApi = zod
    .object({
        id: zod.string().describe('Hog function UUID.'),
        name: zod.string().describe('Hog function name.'),
        type: zod
            .string()
            .nullable()
            .describe('Function type: `destination`, `transformation`, `site_app`, etc. Null if unset.'),
        kind: zod.string().nullable().describe('Function kind sub-classifier; null if unset.'),
        enabled: zod.boolean().describe('Whether the function is currently enabled.'),
        updated_at: zod.string().nullable().describe('ISO-8601 last-modified timestamp.'),
    })
    .describe('One row in `inventory.recent_hog_functions.recent`.')

export type RecentHogFunctionEntryApi = zod.input<typeof RecentHogFunctionEntryApi>
export type RecentHogFunctionEntryApiOutput = zod.output<typeof RecentHogFunctionEntryApi>

export const RecentHogFunctionsApi = zod
    .object({
        total_count: zod.number().describe('Total non-deleted hog functions on the team.'),
        enabled_count: zod.number().describe('Hog functions currently enabled (`enabled=true`).'),
        recent: zod.array(RecentHogFunctionEntryApi).describe('The 5 most recently updated hog functions.'),
    })
    .describe('`inventory.recent_hog_functions` — total + enabled count, plus the 5 most recently modified.')

export type RecentHogFunctionsApi = zod.input<typeof RecentHogFunctionsApi>
export type RecentHogFunctionsApiOutput = zod.output<typeof RecentHogFunctionsApi>

export const RecentHogFlowEntryApi = zod
    .object({
        id: zod.string().describe('Hog flow UUID.'),
        name: zod.string().describe('Hog flow name.'),
        status: zod.string().describe('Flow lifecycle state (e.g. `draft`, `active`, `archived`).'),
        updated_at: zod.string().nullable().describe('ISO-8601 last-modified timestamp.'),
    })
    .describe('One row in `inventory.recent_hog_flows.recent`.')

export type RecentHogFlowEntryApi = zod.input<typeof RecentHogFlowEntryApi>
export type RecentHogFlowEntryApiOutput = zod.output<typeof RecentHogFlowEntryApi>

export const RecentHogFlowsApi = zod
    .object({
        total_count: zod.number().describe('Total hog flows on the team.'),
        active_count: zod.number().describe('Hog flows that are not archived.'),
        recent: zod.array(RecentHogFlowEntryApi).describe('The 5 most recently updated hog flows.'),
    })
    .describe('`inventory.recent_hog_flows` — total + non-archived count, plus the 5 most recently modified.')

export type RecentHogFlowsApi = zod.input<typeof RecentHogFlowsApi>
export type RecentHogFlowsApiOutput = zod.output<typeof RecentHogFlowsApi>

export const RecentNotebookEntryApi = zod
    .object({
        short_id: zod.string().describe('Notebook short ID — pass to the notebooks API to open it.'),
        title: zod.string().describe('Notebook title (may be blank if untitled).'),
        last_modified_at: zod.string().nullable().describe('ISO-8601 last-modified timestamp.'),
    })
    .describe('One row in `inventory.recent_notebooks.recent`.')

export type RecentNotebookEntryApi = zod.input<typeof RecentNotebookEntryApi>
export type RecentNotebookEntryApiOutput = zod.output<typeof RecentNotebookEntryApi>

export const RecentNotebooksApi = zod
    .object({
        total_count: zod.number().describe('Total non-deleted notebooks on the team.'),
        recent: zod.array(RecentNotebookEntryApi).describe('The 5 most recently modified notebooks.'),
    })
    .describe('`inventory.recent_notebooks` — total + the 5 most recently modified.')

export type RecentNotebooksApi = zod.input<typeof RecentNotebooksApi>
export type RecentNotebooksApiOutput = zod.output<typeof RecentNotebooksApi>

export const RecentCohortEntryApi = zod
    .object({
        id: zod.number().describe('Cohort ID.'),
        name: zod.string().describe('Cohort name.'),
        is_static: zod.boolean().describe('True for a one-shot snapshot cohort; false for a dynamic-filter cohort.'),
        count: zod.number().nullable().describe('Membership size when last calculated; null if never calculated.'),
        created_at: zod.string().nullable().describe('ISO-8601 creation timestamp.'),
    })
    .describe('One row in `inventory.recent_cohorts.recent`.')

export type RecentCohortEntryApi = zod.input<typeof RecentCohortEntryApi>
export type RecentCohortEntryApiOutput = zod.output<typeof RecentCohortEntryApi>

export const RecentCohortsApi = zod
    .object({
        total_count: zod.number().describe('Total non-deleted cohorts on the team.'),
        recent: zod.array(RecentCohortEntryApi).describe('The 5 most recently created cohorts.'),
    })
    .describe('`inventory.recent_cohorts` — total + the 5 most recently created.')

export type RecentCohortsApi = zod.input<typeof RecentCohortsApi>
export type RecentCohortsApiOutput = zod.output<typeof RecentCohortsApi>

export const RecentActionEntryApi = zod
    .object({
        id: zod.number().describe('Action ID.'),
        name: zod.string().describe('Action name.'),
        updated_at: zod.string().nullable().describe('ISO-8601 last-modified timestamp.'),
    })
    .describe('One row in `inventory.recent_actions.recent`.')

export type RecentActionEntryApi = zod.input<typeof RecentActionEntryApi>
export type RecentActionEntryApiOutput = zod.output<typeof RecentActionEntryApi>

export const RecentActionsApi = zod
    .object({
        total_count: zod.number().describe('Total non-deleted actions on the team.'),
        recent: zod.array(RecentActionEntryApi).describe('The 5 most recently updated actions.'),
    })
    .describe('`inventory.recent_actions` — total + the 5 most recently modified.')

export type RecentActionsApi = zod.input<typeof RecentActionsApi>
export type RecentActionsApiOutput = zod.output<typeof RecentActionsApi>

export const TopEventEntryApi = zod
    .object({
        window_days: zod
            .number()
            .describe(
                "Rolling lookback window (in days) that every count and timestamp on this row is measured over — these are windowed figures, NOT lifetime totals. A capture gap can collapse a real, high-volume project's in-window counts to near-zero, so a thin `count` here does not by itself mean the project is low-volume: rule out an ingestion gap (compare against a trailing baseline via a direct `execute-sql`) before closing out a surface as unused."
            ),
        event: zod.string().describe('Event name as captured.'),
        count: zod.number().describe('Number of occurrences within the last `window_days` (windowed, not lifetime).'),
        distinct_users: zod
            .number()
            .describe(
                '`uniq(person_id)` over the window — reach. Distinguishes a high-count event firing on one power user from one firing on many users.'
            ),
        recent_24h_count: zod
            .number()
            .describe(
                'Count in just the last 24 hours. Compare to `count \/ window_days` to spot bursts: a ratio well above `1 \/ window_days` means the event is concentrated in the last day.'
            ),
        recent_24h_users: zod
            .number()
            .describe(
                '`uniq(person_id)` over just the last 24 hours. A burst across many users is qualitatively different from one user in a loop.'
            ),
        first_seen_in_window: zod
            .string()
            .nullable()
            .describe(
                "ISO-8601 timestamp of the earliest occurrence within the `window_days` window. Compare to the window start to spot new event types: close to `now` ⇒ likely new or recently bursting; close to the window edge ⇒ has been around at least that long (the window can't tell you when the event \*truly\* first appeared)."
            ),
        last_seen_in_window: zod
            .string()
            .nullable()
            .describe('ISO-8601 timestamp of the most recent occurrence within the `window_days` window.'),
    })
    .describe('One row in `inventory.top_events`.')

export type TopEventEntryApi = zod.input<typeof TopEventEntryApi>
export type TopEventEntryApiOutput = zod.output<typeof TopEventEntryApi>

export const ProjectProfileInventoryApi = zod
    .object({
        project_context: ProjectContextApi.describe(
            'Free-form orientation: human-set product description + registered app URLs.'
        ),
        products_in_use: zod
            .array(zod.string())
            .describe('Product keys this team has completed onboarding for, sorted alphabetically.'),
        product_intents: zod
            .array(ProductIntentEntryApi)
            .describe('Products the team signaled intent to use; useful for spotting stuck onboardings.'),
        integrations: zod
            .array(IntegrationEntryApi)
            .describe('Connected integrations (kind + connection time only — config never surfaced).'),
        external_data_sources: zod
            .array(ExternalDataSourceEntryApi)
            .describe('Connected warehouse sources (excludes soft-deleted).'),
        signal_source_configs: SignalSourceConfigsBucketsApi.describe(
            'Signal source configs split into enabled \/ disabled buckets.'
        ),
        emit_eligibility: EmitEligibilityApi.describe(
            'Whether scout findings can actually reach the inbox for this team — the org-level AI data-processing consent gate and the `signals_scout` source toggle, plus a one-line remediation pointer. Read at cold start to quick-close before doing throwaway work.'
        ),
        scout_fleet: ScoutFleetApi.describe(
            'The other scouts configured on this project, split into enabled \/ disabled, each with its cadence, dry-run posture, last run, and last emit. Read it to see who else is watching this project before investigating a surface a sibling already covers.'
        ),
        existing_inbox_reports: ExistingInboxReportsApi.describe(
            'Counts of reports already in the inbox, grouped by status.'
        ),
        recent_activity: RecentActivityApi.describe(
            'Per-scope counts off the activity log over the recent-activity window — cross-cutting orientation across every entity type (surveys, feature flags, experiments, dashboards, insights, cohorts, notebooks, actions, etc.). Each scope reports `edits` (total log entries), `users` (distinct user count), and `last_edit` (ISO-8601). Use to triage which scope a team has been working in lately before drilling down via the per-entity readers or `advanced-activity-logs-list`.'
        ),
        recent_reviewer_corrections: RecentReviewerCorrectionsApi.describe(
            'Recent human edits to report reviewer lists (before\/after GitHub logins). The strongest ownership precedent available — check it before setting `suggested_reviewers` and fold what it shows into `reviewer:` memory keys.'
        ),
        recent_dashboards: zod
            .array(RecentDashboardEntryApi)
            .describe(
                "Up to 20 dashboards on this team sorted by `last_accessed_at` desc — what the team is currently looking at, not necessarily the most-trafficked. We don't have per-dashboard view counts in Postgres, only the timestamp of the most recent access."
            ),
        recent_surveys: RecentSurveysApi.describe(
            'Surveys orientation: total + active count, plus the 5 most recently updated surveys with id, name, type, status (draft \/ running \/ stopped \/ archived), and updated_at.'
        ),
        recent_feature_flags: RecentFeatureFlagsApi.describe(
            'Feature flag orientation: total + active count, plus the 5 most recently updated non-deleted flags with id, key, name, active, and updated_at.'
        ),
        recent_experiments: RecentExperimentsApi.describe(
            'Experiment orientation: total + running count, plus the 5 most recently updated experiments. The feature_flag_key on each row lets the scout correlate experiments with the `recent_feature_flags` section.'
        ),
        recent_alerts: RecentAlertsApi.describe(
            'Alert orientation: total + enabled count, plus the 5 most recently created alerts with their state and threshold metadata.'
        ),
        recent_hog_functions: RecentHogFunctionsApi.describe(
            'Hog function orientation: total + enabled count, plus the 5 most recently updated destinations \/ transformations the team has wired up via the CDP pipelines.'
        ),
        recent_hog_flows: RecentHogFlowsApi.describe(
            'Hog flow orientation: total + non-archived count, plus the 5 most recently updated automation flows.'
        ),
        recent_notebooks: RecentNotebooksApi.describe(
            'Notebook orientation: total + the 5 most recently modified notebooks — useful signal for what the team has been investigating.'
        ),
        recent_cohorts: RecentCohortsApi.describe(
            'Cohort orientation: total + the 5 most recently created cohorts on the team.'
        ),
        recent_actions: RecentActionsApi.describe(
            'Action orientation: total + the 5 most recently updated actions — useful to anchor agent reasoning about what the team treats as a meaningful interaction.'
        ),
        top_events: zod
            .array(TopEventEntryApi)
            .nullable()
            .describe(
                "Top ~50 events by count over a recent rolling window (each row carries `window_days`), with first\/last seen timestamps within that window. These are WINDOWED counts, not lifetime totals: a capture gap can collapse a real, high-volume project's counts to near-zero here, so rule out an ingestion gap (compare against a trailing baseline via a direct `execute-sql`) before reading thinness as a genuinely low-volume project. `null` if the underlying ClickHouse query failed or timed out (distinct from `[]`, which means the team has no captures in the window). Use the gap between `first_seen_in_window` and `now` to spot new event types or recent bursts."
            ),
    })
    .describe(
        "The deterministic inventory layer of a project profile.\n\nRead this to orient on the team's product mix, integrations, warehouse sources, signal\ncoverage, and existing inbox surface in one tool call. Distinct from `SignalScratchpad`:\nprofile is ground truth from authoritative tables; memory is agent inference."
    )

export type ProjectProfileInventoryApi = zod.input<typeof ProjectProfileInventoryApi>
export type ProjectProfileInventoryApiOutput = zod.output<typeof ProjectProfileInventoryApi>

export const ProjectProfilePayloadApi = zod
    .object({
        inventory: ProjectProfileInventoryApi.describe("Deterministic snapshot of what's true about the project."),
    })
    .describe(
        "Top-level `payload` shape on a `SignalProjectProfile` row.\n\nv1 carries `inventory` only. Phase 7 will add `deltas`, `activity_notes`, and\n`narrative` slots — they're absent (not null) in v1 responses."
    )

export type ProjectProfilePayloadApi = zod.input<typeof ProjectProfilePayloadApi>
export type ProjectProfilePayloadApiOutput = zod.output<typeof ProjectProfilePayloadApi>

export const ProjectProfileApi = zod
    .object({
        profile_id: zod.string().describe('UUID of the `SignalProjectProfile` row.'),
        computed_at: zod.string().describe('ISO-8601 timestamp the profile was built.'),
        expires_at: zod.string().describe('ISO-8601 timestamp after which the profile is considered stale.'),
        source_version: zod
            .string()
            .describe('Schema version of the inventory builder. Bumps invalidate older cached rows.'),
        payload: ProjectProfilePayloadApi.describe('Structured profile content. v1 has `inventory` only.'),
    })
    .describe(
        'Wire shape for the project profile returned by `signals-scout-harness-project-profile-list`.\n\nRead this once at the start of a run (after `skill-get`) to orient on the team. Cache\nis per-team with a soft TTL (`PROFILE_TTL`); the response always reflects either the\nlatest cached profile or a freshly-built one if the cache was stale or the caller passed\n`force_refresh=true`.'
    )

export type ProjectProfileApi = zod.input<typeof ProjectProfileApi>
export type ProjectProfileApiOutput = zod.output<typeof ProjectProfileApi>

export const RunStatusEnumApi = zod
    .enum(['not_started', 'queued', 'in_progress', 'completed', 'failed', 'cancelled'])
    .describe(
        '\* `not_started` - not_started\n\* `queued` - queued\n\* `in_progress` - in_progress\n\* `completed` - completed\n\* `failed` - failed\n\* `cancelled` - cancelled'
    )

export type RunStatusEnumApi = zod.input<typeof RunStatusEnumApi>
export type RunStatusEnumApiOutput = zod.output<typeof RunStatusEnumApi>

export const SignalScoutRunSummaryApi = zod
    .object({
        run_id: zod.string().describe('UUID of the bridge row.'),
        skill_name: zod.string().describe('Canonical skill name the run executed (e.g. `signals-scout-general`).'),
        skill_version: zod.number().describe('Skill version snapshotted at run start.'),
        status: RunStatusEnumApi.describe(
            'Status from the linked TaskRun.\n\n\* `not_started` - not_started\n\* `queued` - queued\n\* `in_progress` - in_progress\n\* `completed` - completed\n\* `failed` - failed\n\* `cancelled` - cancelled'
        ),
        created_at: zod
            .string()
            .describe(
                "ISO-8601 timestamp the bridge row was created — the field `date_from` \/ `date_to` filter and order on. Use this (not `started_at`) as the `date_to` cursor when walking past the 100-row cap, so runs created in the gap between a boundary run's TaskRun and its bridge row aren't skipped."
            ),
        started_at: zod.string().describe('ISO-8601 timestamp the TaskRun was created.'),
        completed_at: zod
            .string()
            .nullable()
            .describe('ISO-8601 timestamp the TaskRun completed; null while still running.'),
        task_id: zod.string().nullish().describe('UUID of the Tasks `Task` the scout span ran inside.'),
        task_run_id: zod.string().nullish().describe('UUID of the Tasks `TaskRun`. Pairs with `task_id` to deep-link.'),
        task_url: zod
            .string()
            .nullish()
            .describe(
                'Relative deep-link to the Tasks UI for this run, e.g. `\/project\/{team_id}\/tasks\/{task_id}?runId={task_run_id}`.'
            ),
        summary: zod
            .string()
            .describe(
                'One-paragraph close-out the scout wrote at end-of-run. Empty string for runs that errored before close-out. The dedupe key for non-emitting runs.'
            ),
        error: zod
            .string()
            .nullish()
            .describe(
                'Full `error_message` from the linked TaskRun, surfaced only for failed\/cancelled runs (null otherwise, including on success). Use `failure_reason` for a concise scan-friendly summary.'
            ),
        failure_reason: zod
            .string()
            .nullish()
            .describe(
                "Concise derived reason the run didn't complete cleanly — the first line of `error` (bounded), or a status-derived fallback. Null unless the run terminated failed\/cancelled. Read this to see at a glance \*why\* a run emitted nothing without pulling full stack traces."
            ),
        emitted_count: zod
            .number()
            .describe(
                'Number of findings this run actually emitted to the inbox. 0 for runs that investigated but surfaced nothing, or ran dry-run \/ before AI approval. `> 0` means the run produced at least one `Signal`.'
            ),
        emitted_finding_ids: zod
            .array(zod.string())
            .describe(
                'The `finding_id`s behind `emitted_count`, in emit order. Each maps to a `Signal` with `source_id = run:<run_id>:finding:<finding_id>`. Empty for non-emitting runs.'
            ),
        emitted_report_ids: zod
            .array(zod.string())
            .describe(
                'The `SignalReport` ids this run authored directly via the `emit_report` channel, in emit order. Separate from `emitted_finding_ids` (weak `emit_signal` findings) — a report-authoring scout writes a full report here instead. Empty for runs that authored no report.'
            ),
        edited_report_ids: zod
            .array(zod.string())
            .describe(
                'The `SignalReport` ids this run mutated via the `edit_report` channel (rewrote title\/summary and\/or appended a note), deduped. Distinct from `emitted_report_ids`: edit can target any inbox report, so these are generally not reports the run authored. Empty for runs that edited no report.'
            ),
        metadata: zod
            .object({
                harness_prompt_version: zod.string().optional(),
                report_channel: zod.string().optional(),
                skill_origin: zod.string().optional(),
                github_guidance: zod.boolean().optional(),
                model: zod.string().optional(),
                runtime_adapter: zod.string().optional(),
                reasoning_effort: zod.string().optional(),
                derived: zod
                    .object({
                        has_emit_report: zod.boolean(),
                        has_edit_report: zod.boolean(),
                        has_self_improvement: zod.boolean(),
                        has_chart: zod.boolean(),
                        has_self_validation: zod.boolean(),
                    })
                    .optional(),
            })
            .describe(
                "Scout-owned per-run context, in two regions. Top-level keys are stamped by the runner at run start. Always present: `harness_prompt_version` (id of the harness prompt build the run was given), `report_channel` (which report tools the run held: `none`, `emit`, `edit`, or `both`), `skill_origin` (`canonical` or `custom`), and `github_guidance` (whether the run got the GitHub evidence section) — the provenance set that says which instructions the run actually got, so runs are only compared against runs of the same shape. Present only when routing overrode the agent-server default: `model`, `runtime_adapter`, and `reasoning_effort`. The nested `derived` object is the harness's own map of boolean run dimensions, computed server-side at finalize: `has_emit_report`, `has_edit_report`, `has_self_improvement`, `has_chart`, and `has_self_validation`. Use `derived` to answer 'what kind of run was this?' instead of parsing the `summary` prose. Note the flags describe the reports the run authored as they stand now, so charts attached to someone else's report via an edit are not counted. A missing `derived` object is unknown, not all-false: the run predates the field, never finalized, or its stamp failed."
            ),
    })
    .describe(
        'Lightweight projection of a `SignalScoutRun` row used by `search-recent-runs`.\n\nStatus and timestamps flow from the linked `tasks.TaskRun`.'
    )

export type SignalScoutRunSummaryApi = zod.input<typeof SignalScoutRunSummaryApi>
export type SignalScoutRunSummaryApiOutput = zod.output<typeof SignalScoutRunSummaryApi>

export const SignalScoutRunDetailApi = zod
    .object({
        run_id: zod.string().describe('UUID of the bridge row.'),
        skill_name: zod.string().describe('Canonical skill name the run executed (e.g. `signals-scout-general`).'),
        skill_version: zod.number().describe('Skill version snapshotted at run start.'),
        status: RunStatusEnumApi.describe(
            'Status from the linked TaskRun.\n\n\* `not_started` - not_started\n\* `queued` - queued\n\* `in_progress` - in_progress\n\* `completed` - completed\n\* `failed` - failed\n\* `cancelled` - cancelled'
        ),
        created_at: zod
            .string()
            .describe(
                "ISO-8601 timestamp the bridge row was created — the field `date_from` \/ `date_to` filter and order on. Use this (not `started_at`) as the `date_to` cursor when walking past the 100-row cap, so runs created in the gap between a boundary run's TaskRun and its bridge row aren't skipped."
            ),
        started_at: zod.string().describe('ISO-8601 timestamp the TaskRun was created.'),
        completed_at: zod
            .string()
            .nullable()
            .describe('ISO-8601 timestamp the TaskRun completed; null while still running.'),
        task_id: zod.string().nullish().describe('UUID of the Tasks `Task` the scout span ran inside.'),
        task_run_id: zod.string().nullish().describe('UUID of the Tasks `TaskRun`. Pairs with `task_id` to deep-link.'),
        task_url: zod
            .string()
            .nullish()
            .describe(
                'Relative deep-link to the Tasks UI for this run, e.g. `\/project\/{team_id}\/tasks\/{task_id}?runId={task_run_id}`.'
            ),
        summary: zod
            .string()
            .describe(
                'One-paragraph close-out the scout wrote at end-of-run. Empty string for runs that errored before close-out. The dedupe key for non-emitting runs.'
            ),
        error: zod
            .string()
            .nullish()
            .describe(
                'Full `error_message` from the linked TaskRun, surfaced only for failed\/cancelled runs (null otherwise, including on success). Use `failure_reason` for a concise scan-friendly summary.'
            ),
        failure_reason: zod
            .string()
            .nullish()
            .describe(
                "Concise derived reason the run didn't complete cleanly — the first line of `error` (bounded), or a status-derived fallback. Null unless the run terminated failed\/cancelled. Read this to see at a glance \*why\* a run emitted nothing without pulling full stack traces."
            ),
        emitted_count: zod
            .number()
            .describe(
                'Number of findings this run actually emitted to the inbox. 0 for runs that investigated but surfaced nothing, or ran dry-run \/ before AI approval. `> 0` means the run produced at least one `Signal`.'
            ),
        emitted_finding_ids: zod
            .array(zod.string())
            .describe(
                'The `finding_id`s behind `emitted_count`, in emit order. Each maps to a `Signal` with `source_id = run:<run_id>:finding:<finding_id>`. Empty for non-emitting runs.'
            ),
        emitted_report_ids: zod
            .array(zod.string())
            .describe(
                'The `SignalReport` ids this run authored directly via the `emit_report` channel, in emit order. Separate from `emitted_finding_ids` (weak `emit_signal` findings) — a report-authoring scout writes a full report here instead. Empty for runs that authored no report.'
            ),
        edited_report_ids: zod
            .array(zod.string())
            .describe(
                'The `SignalReport` ids this run mutated via the `edit_report` channel (rewrote title\/summary and\/or appended a note), deduped. Distinct from `emitted_report_ids`: edit can target any inbox report, so these are generally not reports the run authored. Empty for runs that edited no report.'
            ),
        metadata: zod
            .object({
                harness_prompt_version: zod.string().optional(),
                report_channel: zod.string().optional(),
                skill_origin: zod.string().optional(),
                github_guidance: zod.boolean().optional(),
                model: zod.string().optional(),
                runtime_adapter: zod.string().optional(),
                reasoning_effort: zod.string().optional(),
                derived: zod
                    .object({
                        has_emit_report: zod.boolean(),
                        has_edit_report: zod.boolean(),
                        has_self_improvement: zod.boolean(),
                        has_chart: zod.boolean(),
                        has_self_validation: zod.boolean(),
                    })
                    .optional(),
            })
            .describe(
                "Scout-owned per-run context, in two regions. Top-level keys are stamped by the runner at run start. Always present: `harness_prompt_version` (id of the harness prompt build the run was given), `report_channel` (which report tools the run held: `none`, `emit`, `edit`, or `both`), `skill_origin` (`canonical` or `custom`), and `github_guidance` (whether the run got the GitHub evidence section) — the provenance set that says which instructions the run actually got, so runs are only compared against runs of the same shape. Present only when routing overrode the agent-server default: `model`, `runtime_adapter`, and `reasoning_effort`. The nested `derived` object is the harness's own map of boolean run dimensions, computed server-side at finalize: `has_emit_report`, `has_edit_report`, `has_self_improvement`, `has_chart`, and `has_self_validation`. Use `derived` to answer 'what kind of run was this?' instead of parsing the `summary` prose. Note the flags describe the reports the run authored as they stand now, so charts attached to someone else's report via an edit are not counted. A missing `derived` object is unknown, not all-false: the run predates the field, never finalized, or its stamp failed."
            ),
    })
    .describe(
        'Full `SignalScoutRun` projection used by `get-run`. Same shape as the summary\ntoday; kept distinct so future detail-only extensions (linked Signal rows,\nLLMA token-cost join) can land here without bloating the list response.'
    )

export type SignalScoutRunDetailApi = zod.input<typeof SignalScoutRunDetailApi>
export type SignalScoutRunDetailApiOutput = zod.output<typeof SignalScoutRunDetailApi>

export const suggestedReviewerApiGithubLoginMax = 200

export const suggestedReviewerApiReasonMax = 500

export const SuggestedReviewerApi = zod
    .object({
        github_login: zod
            .string()
            .max(suggestedReviewerApiGithubLoginMax)
            .optional()
            .describe(
                'GitHub login (case-insensitive, stored lowercased) — e.g. `octocat`, no `@`, no display name. Resolve one via `scout-members-list` (each member row carries a resolved `github_login`) or git history when you only have a name.'
            ),
        user_uuid: zod
            .uuid()
            .optional()
            .describe(
                "PostHog user UUID (e.g. from `scout-members-list`, or an entity's `created_by`). Resolved server-side to the member's linked GitHub login — use this when you know the PostHog user but not their GitHub handle. Must be a concrete UUID; the `@me` alias is not valid here."
            ),
        reason: zod
            .string()
            .max(suggestedReviewerApiReasonMax)
            .nullish()
            .describe(
                "One sentence of evidence for WHY this person: what ties them to the affected surface (e.g. 'authored 4 of the last 10 commits touching products\/tracing\/mcp\/', 'human correction routed the prior tracing report to them'). Persisted on the report so the routing is auditable — always set it when you can name the evidence; 'precedent' alone is weak, prefer code-derived ownership."
            ),
    })
    .describe(
        "One suggested reviewer — identified by `github_login`, `user_uuid`, or both.\n\nThe server canonicalizes each entry to a lowercased GitHub login: a `user_uuid` is resolved to the\norg member's linked GitHub login (and wins over a supplied `github_login` when both are given). A\n`user_uuid` that isn't an org member of this team with a linked GitHub identity is rejected — so a\nreviewer is never silently dropped."
    )

export type SuggestedReviewerApi = zod.input<typeof SuggestedReviewerApi>
export type SuggestedReviewerApiOutput = zod.output<typeof SuggestedReviewerApi>

export const editReportRequestApiTitleMax = 300

export const editReportRequestApiSuggestedReviewersMax = 10

export const editReportRequestApiChartsMax = 20

export const EditReportRequestApi = zod
    .object({
        report_id: zod.string().describe('Id of the report to edit (must belong to this project).'),
        title: zod
            .string()
            .max(editReportRequestApiTitleMax)
            .nullish()
            .describe(
                'Optional new title. Conventional-commit style (`type(scope): description`) renders with type\/scope styling. The pipeline may later re-research and overwrite it.'
            ),
        summary: zod
            .string()
            .nullish()
            .describe(
                'Optional new summary. Markdown is supported (headings, lists, code, links; images are not rendered); lead with one plain declarative sentence — it becomes the inbox card headline. The pipeline may later re-research and overwrite it.'
            ),
        append_note: zod
            .string()
            .nullish()
            .describe("Optional free-form note to append to the report's work log (attributed to this scout)."),
        suggested_reviewers: zod
            .array(SuggestedReviewerApi)
            .max(editReportRequestApiSuggestedReviewersMax)
            .optional()
            .describe(
                'Optional reviewers to set on the report (each a `github_login` and\/or `user_uuid`), replacing any existing list. Use this to route a report that surfaced with no reviewer — it re-runs autostart, so a report that was missing a qualifying reviewer can now open a draft PR. An empty list is a no-op (existing reviewers are left untouched, never cleared).'
            ),
        charts: zod
            .array(ReportChartApi)
            .max(editReportRequestApiChartsMax)
            .nullish()
            .describe(
                "The full set of charts the report should show. Replaces the report's charts rather than adding to them, the way `summary` replaces the summary — so send every chart you want kept. Omit the field (or send null) to leave the report's existing charts untouched, and send an empty list to take them all down."
            ),
    })
    .describe(
        "Request body for `edit-report`. Can target ANY of the team's inbox reports, not just scout-authored ones."
    )

export type EditReportRequestApi = zod.input<typeof EditReportRequestApi>
export type EditReportRequestApiOutput = zod.output<typeof EditReportRequestApi>

export const EditReportResponseApi = zod.object({
    report_id: zod.string().describe('Id of the edited report.'),
    updated_fields: zod
        .array(zod.string())
        .describe('Which presentation fields changed (e.g. `title`, `summary`); empty if only a note was appended.'),
    note_appended: zod.boolean().describe('Whether a note artefact was appended.'),
    reviewers_set: zod.boolean().describe("Whether the report's suggested reviewers were replaced."),
    charts_set: zod
        .number()
        .nullable()
        .describe(
            "How many charts the report now shows, or null if the edit left its charts as they were (the field omitted, or a re-send of what was already stored). 0 means the edit took the report's charts down."
        ),
})

export type EditReportResponseApi = zod.input<typeof EditReportResponseApi>
export type EditReportResponseApiOutput = zod.output<typeof EditReportResponseApi>

export const AutonomyPriorityEnumApi = zod
    .enum(['P0', 'P1', 'P2', 'P3', 'P4'])
    .describe('\* `P0` - P0\n\* `P1` - P1\n\* `P2` - P2\n\* `P3` - P3\n\* `P4` - P4')

export type AutonomyPriorityEnumApi = zod.input<typeof AutonomyPriorityEnumApi>
export type AutonomyPriorityEnumApiOutput = zod.output<typeof AutonomyPriorityEnumApi>

export const signalScoutEmissionApiWeightMin = 0
export const signalScoutEmissionApiWeightMax = 1

export const signalScoutEmissionApiConfidenceMin = 0
export const signalScoutEmissionApiConfidenceMax = 1

export const SignalScoutEmissionApi = zod
    .object({
        id: zod.uuid(),
        run_id: zod.string().describe('UUID of the `SignalScoutRun` that emitted this finding.'),
        finding_id: zod
            .string()
            .describe("Stable id the finding was emitted under; matches an entry in the run's `emitted_finding_ids`."),
        description: zod
            .string()
            .describe("The emitted finding prose — the signal's `description` as surfaced to the inbox."),
        weight: zod
            .number()
            .min(signalScoutEmissionApiWeightMin)
            .max(signalScoutEmissionApiWeightMax)
            .describe("Agent's weight for the signal in [0, 1]. Drives ranking in the inbox."),
        confidence: zod
            .number()
            .min(signalScoutEmissionApiConfidenceMin)
            .max(signalScoutEmissionApiConfidenceMax)
            .describe("Agent's confidence the finding is real in [0, 1]."),
        severity: zod
            .union([AutonomyPriorityEnumApi, zod.null()])
            .describe(
                "Optional severity tag — one of P0, P1, P2, P3, P4 — or null if the run didn't set one.\n\n\* `P0` - P0\n\* `P1` - P1\n\* `P2` - P2\n\* `P3` - P3\n\* `P4` - P4"
            ),
        tags: zod
            .array(zod.string())
            .describe(
                'Slug tags the scout attached to this finding (lowercase kebab-case, e.g. `cost-spike`). Empty list when the run set none.'
            ),
        source_id: zod
            .string()
            .describe(
                'Deterministic `run:<run_id>:finding:<finding_id>` — the join key into the underlying signal store.'
            ),
        emitted_at: zod.iso.datetime({ offset: true }).describe('ISO-8601 timestamp the finding was emitted.'),
    })
    .describe(
        'One finding a scout run emitted to the inbox — the persisted, queryable record of\n\*what\* the run surfaced, returned by `scout-runs-emissions-list`. The emitted text\nlives in `description`; `source_id` is the join key (`run:<run_id>:finding:<finding_id>`)\nback into the underlying signal store.'
    )

export type SignalScoutEmissionApi = zod.input<typeof SignalScoutEmissionApi>
export type SignalScoutEmissionApiOutput = zod.output<typeof SignalScoutEmissionApi>

export const LinkedSignalReportApi = zod
    .object({
        id: zod.uuid().describe('UUID of the linked `SignalReport`.'),
        title: zod
            .string()
            .nullable()
            .describe("LLM-generated report title, or null if the report hasn't been summarised yet."),
        status: zod.string().describe('Current report status (e.g. `potential`, `ready`, `resolved`).'),
    })
    .describe(
        'Minimal inbox `SignalReport` projection for the scout reverse lookup — just enough\nfor the scout UI to render a clickable chip and deep-link into the inbox, which loads\nthe full report itself.'
    )

export type LinkedSignalReportApi = zod.input<typeof LinkedSignalReportApi>
export type LinkedSignalReportApiOutput = zod.output<typeof LinkedSignalReportApi>

export const ScoutEmissionReportLinkApi = zod
    .object({
        finding_id: zod.string().describe('Stable id the finding was emitted under.'),
        source_id: zod
            .string()
            .describe('Deterministic `run:<run_id>:finding:<finding_id>` join key into the signal store.'),
        report: zod
            .union([LinkedSignalReportApi, zod.null()])
            .describe('The inbox report this finding linked to, or null if none could be resolved.'),
    })
    .describe(
        "One finding the run emitted, paired with the inbox report (if any) its signal grouped into.\n\nBest-effort reverse of the report -> signals link: `report` is null when the finding hasn't\ngrouped into a report yet, was de-duplicated away, or its signal was deleted."
    )

export type ScoutEmissionReportLinkApi = zod.input<typeof ScoutEmissionReportLinkApi>
export type ScoutEmissionReportLinkApiOutput = zod.output<typeof ScoutEmissionReportLinkApi>

export const reportEvidenceApiWeightMin = 0

export const ReportEvidenceApi = zod
    .object({
        description: zod
            .string()
            .describe('Prose for this observation. Embedded and rendered to the safety\/research surfaces.'),
        source_id: zod
            .string()
            .describe('Stable id for this observation within the report (lets a later edit address it).'),
        weight: zod
            .number()
            .min(reportEvidenceApiWeightMin)
            .optional()
            .describe('Optional per-signal weight (defaults to 1.0). Scouts rarely need to set this.'),
    })
    .describe('One observation backing an authored report — becomes a bound signal row on the report.')

export type ReportEvidenceApi = zod.input<typeof ReportEvidenceApi>
export type ReportEvidenceApiOutput = zod.output<typeof ReportEvidenceApi>

export const ActionabilityEnumApi = zod
    .enum(['immediately_actionable', 'requires_human_input', 'not_actionable'])
    .describe(
        '\* `immediately_actionable` - immediately_actionable\n\* `requires_human_input` - requires_human_input\n\* `not_actionable` - not_actionable'
    )

export type ActionabilityEnumApi = zod.input<typeof ActionabilityEnumApi>
export type ActionabilityEnumApiOutput = zod.output<typeof ActionabilityEnumApi>

export const emitReportRequestApiTitleMax = 300

export const emitReportRequestApiAlreadyAddressedDefault = false
export const emitReportRequestApiSuggestedReviewersMax = 10

export const emitReportRequestApiChartsMax = 20

export const EmitReportRequestApi = zod
    .object({
        title: zod
            .string()
            .max(emitReportRequestApiTitleMax)
            .describe(
                'One-line report title the inbox shows. Conventional-commit style (`type(scope): description`, e.g. `fix(insights): missing series color`) renders with type\/scope styling.'
            ),
        summary: zod
            .string()
            .describe(
                'The report body the inbox shows. Markdown is supported (headings, lists, code, links; images are not rendered). Lead with one plain declarative sentence — the inbox card uses your first line verbatim as the headline (~140 chars, emphasis stripped), then renders the full markdown in the detail view.'
            ),
        evidence: zod
            .array(ReportEvidenceApi)
            .min(1)
            .describe('The observations backing the report — each becomes a bound signal. At least one.'),
        actionability_explanation: zod
            .string()
            .describe('2-3 sentence evidence-grounded justification for the actionability call below.'),
        actionability: ActionabilityEnumApi.describe(
            "The scout's actionability call: `immediately_actionable` -> the report surfaces READY; `requires_human_input` -> PENDING_INPUT; `not_actionable` -> suppressed. A safety-judge failure suppresses the report regardless.\n\n\* `immediately_actionable` - immediately_actionable\n\* `requires_human_input` - requires_human_input\n\* `not_actionable` - not_actionable"
        ),
        already_addressed: zod
            .boolean()
            .default(emitReportRequestApiAlreadyAddressedDefault)
            .describe(
                'Whether the issue is already being handled — fixed in recent changes, or with a fix in flight (an open PR, a recently active branch, an assigned \/ in-progress issue or agent task). Gates autostart, so a wrong `false` opens a duplicate PR. Tracked separately.'
            ),
        repository: zod
            .string()
            .nullish()
            .describe(
                "Optional repo for autostart (opening a draft PR): `owner\/repo` targets that repo, the `NO_REPO` sentinel opts out (report lands without a PR), and omitting it triggers free-form selection across the team's repos — the slow path on a many-repo team, so pass `owner\/repo` when you know it."
            ),
        priority: zod
            .union([AutonomyPriorityEnumApi, zod.null()])
            .optional()
            .describe(
                'Optional priority (`P0`-`P4`). Required for autostart; pair with `priority_explanation`.\n\n\* `P0` - P0\n\* `P1` - P1\n\* `P2` - P2\n\* `P3` - P3\n\* `P4` - P4'
            ),
        priority_explanation: zod
            .string()
            .nullish()
            .describe('2-3 sentence justification for `priority`. Required when `priority` is set.'),
        suggested_reviewers: zod
            .array(SuggestedReviewerApi)
            .max(emitReportRequestApiSuggestedReviewersMax)
            .optional()
            .describe(
                "Optional reviewers to route the report to (each a `github_login` and\/or `user_uuid`). This is the primary way a report reaches a human — the inbox floats a reviewer's own reports to the top of their inbox even when no PR is involved — so set it whenever you can name a plausible owner. It also gates autostart: a PR opens only if at least one reviewer clears their autonomy threshold."
            ),
        charts: zod
            .array(ReportChartApi)
            .max(emitReportRequestApiChartsMax)
            .optional()
            .describe(
                'Optional charts to attach to the report — the inbox renders them inline, so a metric move is something the reader sees rather than a number they take on trust. Attach one whenever the finding rests on a trend, a spike, or a comparison you already queried.'
            ),
    })
    .describe('Request body for `emit-report`. Run attribution is taken from the URL path.')

export type EmitReportRequestApi = zod.input<typeof EmitReportRequestApi>
export type EmitReportRequestApiOutput = zod.output<typeof EmitReportRequestApi>

export const EmitReportResponseApi = zod.object({
    report_id: zod
        .string()
        .nullable()
        .describe(
            "The authored report's id (null only when a preflight gate skipped the call). Returned even when suppressed, so you can edit\/dedup against it."
        ),
    report_status: zod
        .string()
        .nullable()
        .describe('Birth status: `ready` | `pending_input` | `suppressed`, or null when gate-skipped.'),
    emitted: zod.boolean().describe('True when the report actually surfaced in the inbox (READY or PENDING_INPUT).'),
    skipped_reason: zod
        .string()
        .nullable()
        .describe(
            '`scout_config_missing` | `scout_emit_disabled` | `ai_processing_not_approved` | `source_disabled` | null when not gate-skipped.'
        ),
    safety_explanation: zod
        .string()
        .nullable()
        .describe('When the safety judge suppressed the report, why; null when safe.'),
    remediation: zod
        .string()
        .nullable()
        .describe(
            "One-line, actionable next step when `skipped_reason` is set and the block is fixable (e.g. an org admin must approve AI data processing). Null when the report was authored or the skip isn't something the scout can act on."
        ),
})

export type EmitReportResponseApi = zod.input<typeof EmitReportResponseApi>
export type EmitReportResponseApiOutput = zod.output<typeof EmitReportResponseApi>

export const EvidenceEntryApi = zod
    .object({
        source_product: zod
            .string()
            .describe('Source the citation came from (`error_tracking`, `session_replay`, `logs`, ...).'),
        summary: zod.string().describe('One-sentence prose about why this evidence supports the finding.'),
        entity_id: zod
            .string()
            .nullish()
            .describe('Optional ID of the cited entity (issue id, recording id, log query id).'),
    })
    .describe('One citation attached to a finding. Mirrors `SignalsScoutEvidenceEntry`.')

export type EvidenceEntryApi = zod.input<typeof EvidenceEntryApi>
export type EvidenceEntryApiOutput = zod.output<typeof EvidenceEntryApi>

export const TimeRangeApi = zod.object({
    date_from: zod.string().describe("ISO-8601 inclusive lower bound for the finding's window."),
    date_to: zod.string().describe("ISO-8601 inclusive upper bound for the finding's window."),
})

export type TimeRangeApi = zod.input<typeof TimeRangeApi>
export type TimeRangeApiOutput = zod.output<typeof TimeRangeApi>

export const emitFindingRequestApiDescriptionMax = 50000

export const emitFindingRequestApiConfidenceMin = 0
export const emitFindingRequestApiConfidenceMax = 1

export const emitFindingRequestApiEvidenceMax = 20

export const emitFindingRequestApiTagsItemMax = 50

export const emitFindingRequestApiTagsMax = 10

export const emitFindingRequestApiFindingIdMax = 100

export const EmitFindingRequestApi = zod
    .object({
        description: zod
            .string()
            .max(emitFindingRequestApiDescriptionMax)
            .describe("Canonical evidence-bundle prose. Becomes the signal's `description`."),
        confidence: zod
            .number()
            .min(emitFindingRequestApiConfidenceMin)
            .max(emitFindingRequestApiConfidenceMax)
            .describe("Agent's confidence the finding is real in [0, 1]. Persisted in `extra`."),
        evidence: zod
            .array(EvidenceEntryApi)
            .max(emitFindingRequestApiEvidenceMax)
            .describe('Citations supporting the finding. Capped at 20 entries.'),
        hypothesis: zod.string().nullish().describe('Optional one-line hypothesis the finding tests.'),
        severity: zod
            .union([AutonomyPriorityEnumApi, zod.null()])
            .optional()
            .describe(
                'Optional severity tag — one of P0, P1, P2, P3, P4. Informational only.\n\n\* `P0` - P0\n\* `P1` - P1\n\* `P2` - P2\n\* `P3` - P3\n\* `P4` - P4'
            ),
        dedupe_keys: zod
            .array(zod.string())
            .optional()
            .describe('Optional keys for downstream dedupe (e.g. `error_tracking_issue:<id>`).'),
        tags: zod
            .array(zod.string().max(emitFindingRequestApiTagsItemMax))
            .max(emitFindingRequestApiTagsMax)
            .optional()
            .describe(
                "Optional category tags as lowercase kebab-case slugs (e.g. `cost-spike`, `silent-failure`), max 10. Reuse the vocabulary in your `tags:<domain>:taxonomy` scratchpad entry when a tag fits; coin a new slug when a genuinely new category emerges. Near-miss formats are normalized to slugs; persisted in the signal's `extra.tags` and on the emission row."
            ),
        time_range: zod
            .union([TimeRangeApi, zod.null()])
            .optional()
            .describe('Optional time window the finding refers to.'),
        mcp_trace_id: zod.string().nullish().describe('Optional MCP trace id for cross-system debugging.'),
        finding_id: zod
            .string()
            .max(emitFindingRequestApiFindingIdMax)
            .nullish()
            .describe(
                "Stable id for this finding, baked into the signal's source_id for traceability. NOT a dedupe key — re-emitting the same id creates another signal."
            ),
    })
    .describe('Request body for `emit-finding`. Run attribution is taken from the URL path.')

export type EmitFindingRequestApi = zod.input<typeof EmitFindingRequestApi>
export type EmitFindingRequestApiOutput = zod.output<typeof EmitFindingRequestApi>

export const EmitFindingResponseApi = zod.object({
    finding_id: zod.string().describe('Stable id for the finding (echoed back from request, or generated).'),
    emitted: zod.boolean().describe('Whether `emit_signal` was actually fired.'),
    skipped_reason: zod
        .string()
        .nullable()
        .describe('`ai_processing_not_approved` | `source_disabled` | null when emitted normally.'),
    remediation: zod
        .string()
        .nullable()
        .describe(
            "One-line, actionable next step when `skipped_reason` is set and the block is fixable (e.g. an org admin must approve AI data processing). Null when emitted normally or the skip isn't something the scout can act on."
        ),
})

export type EmitFindingResponseApi = zod.input<typeof EmitFindingResponseApi>
export type EmitFindingResponseApiOutput = zod.output<typeof EmitFindingResponseApi>

export const scoutRunIdsBatchRequestApiRunIdsMax = 200

export const ScoutRunIdsBatchRequestApi = zod
    .object({
        run_ids: zod
            .array(zod.uuid())
            .max(scoutRunIdsBatchRequestApiRunIdsMax)
            .describe(
                'UUIDs of the `SignalScoutRun` rows to resolve in one batch. Run ids belonging to another team are silently ignored (they contribute no rows) rather than failing the whole request. Capped at 200 ids per call.'
            ),
    })
    .describe(
        "Request body for the batched emissions \/ emission-reports lookups: the set of run UUIDs to\nresolve in one call. Collapses the findings UI's old per-run fan-out (one request — and for the\nreports lookup, one ClickHouse round-trip — per emitted run) into a single request."
    )

export type ScoutRunIdsBatchRequestApi = zod.input<typeof ScoutRunIdsBatchRequestApi>
export type ScoutRunIdsBatchRequestApiOutput = zod.output<typeof ScoutRunIdsBatchRequestApi>

export const FleetFindingsSummaryApi = zod
    .object({
        count: zod
            .number()
            .describe(
                "Total findings the fleet emitted in the window — the sum of each run's `emitted_count`, over the most recent 120 runs that produced output."
            ),
        scout_count: zod
            .number()
            .describe(
                "Number of distinct scouts (skills) that produced output in the window — emitted a finding, or authored\/edited an inbox report that survives the 50-report cap (a report-only scout whose touched reports all fell outside the cap is not counted, matching the findings page's scout filter)."
            ),
        authored_report_count: zod
            .number()
            .describe(
                'Number of distinct inbox reports scouts authored via `emit_report`, deduped across runs, over the same most-recent-120-output-runs set as `count`, capped to the 50 most recently touched reports (the same slice the findings page lists).'
            ),
        edited_report_count: zod
            .number()
            .describe(
                'Number of distinct inbox reports scouts edited via `edit_report`, deduped across runs, over the same most-recent-120-output-runs set as `count`, capped to the 50 most recently touched reports (the same slice the findings page lists) and excluding reports also authored within that set (authoring supersedes an edit; a report whose authoring run falls outside the cap counts as edited).'
            ),
        latest_at: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe(
                'ISO-8601 timestamp of the most recent output run (TaskRun completion, falling back to run creation), or null when nothing was produced in the window.'
            ),
    })
    .describe(
        'Fleet-wide tally of recent scout output — legacy `emit_signal` findings plus reports\nauthored\/edited via the report channel. Backs the \"Scout findings\" callout so it renders\nfrom one cheap query instead of the client walking the whole paginated runs window.'
    )

export type FleetFindingsSummaryApi = zod.input<typeof FleetFindingsSummaryApi>
export type FleetFindingsSummaryApiOutput = zod.output<typeof FleetFindingsSummaryApi>

export const ScratchpadEntryApi = zod
    .object({
        key: zod.string().describe('Agent-chosen semantic key, unique per team.'),
        content: zod
            .string()
            .describe(
                'Prose content for prompt injection. Blank when the search projected it out (`keys_only=true`); truncated to a preview when `content_max_chars` was set.'
            ),
        created_at: zod.string().nullable().describe('ISO-8601 creation timestamp.'),
        updated_at: zod.string().nullable().describe('ISO-8601 last-write timestamp.'),
        created_by_run_id: zod.string().nullable().describe('Run that wrote this entry, or null if human-authored.'),
        created_by_skill: zod
            .string()
            .nullish()
            .describe(
                'Canonical skill name of the scout that created this entry (e.g. `signals-scout-apm`), or null if human-authored.'
            ),
        created_by_run_url: zod
            .string()
            .nullish()
            .describe(
                "Relative Tasks UI deep-link to the run that created this entry, or null if the run linkage isn't captured."
            ),
    })
    .describe('`SignalScratchpad` projection used by `search-memory` and `remember`.')

export type ScratchpadEntryApi = zod.input<typeof ScratchpadEntryApi>
export type ScratchpadEntryApiOutput = zod.output<typeof ScratchpadEntryApi>

export const rememberRequestApiKeyMax = 300

export const rememberRequestApiContentMax = 50000

export const RememberRequestApi = zod
    .object({
        key: zod
            .string()
            .max(rememberRequestApiKeyMax)
            .describe(
                "Agent-chosen semantic key, unique per team; re-using a key overwrites the entry in place. Key off the \*stable identity\* of what you're tracking — never embed a date, timestamp, or run id (that mints a new row every run and breaks dedupe). For run state\/cursors, use one fixed key and keep the timestamp in `content`."
            ),
        content: zod
            .string()
            .max(rememberRequestApiContentMax)
            .describe('Prose to write. Read verbatim into future prompts.'),
        run_id: zod
            .uuid()
            .nullish()
            .describe(
                "Run that authored this memory; persisted as `created_by_run_id` for lineage. Best-effort — a `run_id` that isn't a run on this project is dropped (lineage left null), not rejected, so the memory write is never lost."
            ),
    })
    .describe('Request body for `remember`.')

export type RememberRequestApi = zod.input<typeof RememberRequestApi>
export type RememberRequestApiOutput = zod.output<typeof RememberRequestApi>

export const forgetRequestApiKeyMax = 300

export const ForgetRequestApi = zod
    .object({
        key: zod.string().max(forgetRequestApiKeyMax).describe('Memory key to delete.'),
    })
    .describe('Request body for `forget`.')

export type ForgetRequestApi = zod.input<typeof ForgetRequestApi>
export type ForgetRequestApiOutput = zod.output<typeof ForgetRequestApi>

export const ForgetResponseApi = zod.object({
    deleted: zod.boolean().describe("Whether a row was actually removed (false if the key didn't exist)."),
})

export type ForgetResponseApi = zod.input<typeof ForgetResponseApi>
export type ForgetResponseApiOutput = zod.output<typeof ForgetResponseApi>

export const SignalSourceConfigSourceProductEnumApi = zod
    .enum([
        'session_replay',
        'llm_analytics',
        'github',
        'linear',
        'jira',
        'zendesk',
        'conversations',
        'error_tracking',
        'pganalyze',
        'signals_scout',
        'logs',
        'health_checks',
        'endpoints',
        'replay_vision',
        'analytics',
        'freshdesk',
        'freshservice',
        'front',
        'gorgias',
        'kustomer',
        'dixa',
        'plain',
        'gitlab',
        'gitea',
        'shortcut',
        'sentry',
        'rollbar',
        'bugsnag',
        'honeybadger',
        'raygun',
        'snyk',
        'sonarqube',
        'semgrep',
        'rapid7_insightvm',
        'featurebase',
        'frill',
        'aha',
        'uservoice',
        'productboard',
        'canny',
        'asknicely',
        'retently',
        'appfigures',
        'appfollow',
        'judgeme_reviews',
        'intercom',
        'hubspot',
        'engineering_analytics',
        'google_search_console',
    ])
    .describe(
        '\* `session_replay` - Session replay\n\* `llm_analytics` - LLM analytics\n\* `github` - GitHub\n\* `linear` - Linear\n\* `jira` - Jira\n\* `zendesk` - Zendesk\n\* `conversations` - Conversations\n\* `error_tracking` - Error tracking\n\* `pganalyze` - pganalyze\n\* `signals_scout` - Signals scout\n\* `logs` - Logs\n\* `health_checks` - Health checks\n\* `endpoints` - Endpoints\n\* `replay_vision` - Replay Vision\n\* `analytics` - Product analytics\n\* `freshdesk` - Freshdesk\n\* `freshservice` - Freshservice\n\* `front` - Front\n\* `gorgias` - Gorgias\n\* `kustomer` - Kustomer\n\* `dixa` - Dixa\n\* `plain` - Plain\n\* `gitlab` - GitLab\n\* `gitea` - Gitea\n\* `shortcut` - Shortcut\n\* `sentry` - Sentry\n\* `rollbar` - Rollbar\n\* `bugsnag` - Bugsnag\n\* `honeybadger` - Honeybadger\n\* `raygun` - Raygun\n\* `snyk` - Snyk\n\* `sonarqube` - SonarQube\n\* `semgrep` - Semgrep\n\* `rapid7_insightvm` - Rapid7 InsightVM\n\* `featurebase` - Featurebase\n\* `frill` - Frill\n\* `aha` - Aha\n\* `uservoice` - UserVoice\n\* `productboard` - Productboard\n\* `canny` - Canny\n\* `asknicely` - AskNicely\n\* `retently` - Retently\n\* `appfigures` - Appfigures\n\* `appfollow` - AppFollow\n\* `judgeme_reviews` - Judge.me\n\* `intercom` - Intercom\n\* `hubspot` - HubSpot\n\* `engineering_analytics` - Engineering analytics\n\* `google_search_console` - Google Search Console'
    )

export type SignalSourceConfigSourceProductEnumApi = zod.input<typeof SignalSourceConfigSourceProductEnumApi>
export type SignalSourceConfigSourceProductEnumApiOutput = zod.output<typeof SignalSourceConfigSourceProductEnumApi>

export const SignalSourceConfigSourceTypeEnumApi = zod
    .enum([
        'session_analysis_cluster',
        'evaluation',
        'evaluation_report',
        'issue',
        'ticket',
        'issue_created',
        'issue_reopened',
        'issue_spiking',
        'cross_source_issue',
        'alert_state_change',
        'health_issue',
        'endpoint_execution_failed',
        'endpoint_breakdown_limit_exceeded',
        'scanner_finding',
        'anomaly_investigation',
        'ci_flaky_check',
        'ci_broken_default_branch',
        'ci_duration_regression',
    ])
    .describe(
        '\* `session_analysis_cluster` - Session analysis cluster\n\* `evaluation` - Evaluation\n\* `evaluation_report` - Evaluation report\n\* `issue` - Issue\n\* `ticket` - Ticket\n\* `issue_created` - Issue created\n\* `issue_reopened` - Issue reopened\n\* `issue_spiking` - Issue spiking\n\* `cross_source_issue` - Cross source issue\n\* `alert_state_change` - Alert state change\n\* `health_issue` - Health issue\n\* `endpoint_execution_failed` - Endpoint execution failed\n\* `endpoint_breakdown_limit_exceeded` - Endpoint breakdown limit exceeded\n\* `scanner_finding` - Scanner finding\n\* `anomaly_investigation` - Anomaly investigation\n\* `ci_flaky_check` - CI flaky check\n\* `ci_broken_default_branch` - CI broken default branch\n\* `ci_duration_regression` - CI duration regression'
    )

export type SignalSourceConfigSourceTypeEnumApi = zod.input<typeof SignalSourceConfigSourceTypeEnumApi>
export type SignalSourceConfigSourceTypeEnumApiOutput = zod.output<typeof SignalSourceConfigSourceTypeEnumApi>

export const SignalSourceConfigApi = zod.object({
    id: zod.uuid(),
    source_product: SignalSourceConfigSourceProductEnumApi,
    source_type: SignalSourceConfigSourceTypeEnumApi,
    enabled: zod.boolean().optional(),
    config: zod.unknown().optional(),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
    status: zod.string().nullable(),
})

export type SignalSourceConfigApi = zod.input<typeof SignalSourceConfigApi>
export type SignalSourceConfigApiOutput = zod.output<typeof SignalSourceConfigApi>

export const PaginatedSignalSourceConfigListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(SignalSourceConfigApi),
})

export type PaginatedSignalSourceConfigListApi = zod.input<typeof PaginatedSignalSourceConfigListApi>
export type PaginatedSignalSourceConfigListApiOutput = zod.output<typeof PaginatedSignalSourceConfigListApi>

export const PatchedSignalSourceConfigApi = zod.object({
    id: zod.uuid().optional(),
    source_product: SignalSourceConfigSourceProductEnumApi.optional(),
    source_type: SignalSourceConfigSourceTypeEnumApi.optional(),
    enabled: zod.boolean().optional(),
    config: zod.unknown().optional(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).optional(),
    status: zod.string().nullish(),
})

export type PatchedSignalSourceConfigApi = zod.input<typeof PatchedSignalSourceConfigApi>
export type PatchedSignalSourceConfigApiOutput = zod.output<typeof PatchedSignalSourceConfigApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const signalUserAutonomyConfigApiSlackNotificationChannelMax = 255

export const SignalUserAutonomyConfigApi = zod.object({
    id: zod.uuid(),
    user: _UserApi,
    autostart_priority: zod.union([AutonomyPriorityEnumApi, BlankEnumApi, zod.null()]).optional(),
    slack_notification_integration_id: zod
        .number()
        .nullable()
        .describe(
            'ID of the Slack Integration to deliver inbox-item notifications through, or null when notifications are disabled.'
        ),
    slack_notification_channel: zod
        .string()
        .max(signalUserAutonomyConfigApiSlackNotificationChannelMax)
        .nullish()
        .describe(
            'Slack channel target in the same `channel_id|#channel-name` shape PostHog uses elsewhere (only the channel id is required). Null disables Slack notifications.'
        ),
    slack_notification_min_priority: zod
        .union([AutonomyPriorityEnumApi, BlankEnumApi, zod.null()])
        .optional()
        .describe(
            'Minimum report priority that triggers a Slack notification. P0 is highest. Null means notify on every priority (and reports without a priority judgment).\n\n\* `P0` - P0\n\* `P1` - P1\n\* `P2` - P2\n\* `P3` - P3\n\* `P4` - P4'
        ),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
})

export type SignalUserAutonomyConfigApi = zod.input<typeof SignalUserAutonomyConfigApi>
export type SignalUserAutonomyConfigApiOutput = zod.output<typeof SignalUserAutonomyConfigApi>

export const SignalNodeApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type SignalNodeApi = zod.input<typeof SignalNodeApi>
export type SignalNodeApiOutput = zod.output<typeof SignalNodeApi>

export const SignalSourceProductApi = zod
    .enum([
        'session_replay',
        'llm_analytics',
        'github',
        'linear',
        'jira',
        'zendesk',
        'conversations',
        'error_tracking',
        'endpoints',
        'pganalyze',
        'signals_scout',
        'logs',
        'health_checks',
        'replay_vision',
        'analytics',
        'freshdesk',
        'freshservice',
        'front',
        'gorgias',
        'kustomer',
        'dixa',
        'plain',
        'gitlab',
        'gitea',
        'shortcut',
        'sentry',
        'rollbar',
        'bugsnag',
        'honeybadger',
        'raygun',
        'snyk',
        'sonarqube',
        'semgrep',
        'rapid7_insightvm',
        'featurebase',
        'frill',
        'aha',
        'uservoice',
        'productboard',
        'canny',
        'asknicely',
        'retently',
        'appfigures',
        'appfollow',
        'judgeme_reviews',
        'intercom',
        'hubspot',
        'engineering_analytics',
        'google_search_console',
    ])
    .describe(
        '\* `session_replay` - session_replay\n\* `llm_analytics` - llm_analytics\n\* `github` - github\n\* `linear` - linear\n\* `jira` - jira\n\* `zendesk` - zendesk\n\* `conversations` - conversations\n\* `error_tracking` - error_tracking\n\* `endpoints` - endpoints\n\* `pganalyze` - pganalyze\n\* `signals_scout` - signals_scout\n\* `logs` - logs\n\* `health_checks` - health_checks\n\* `replay_vision` - replay_vision\n\* `analytics` - analytics\n\* `freshdesk` - freshdesk\n\* `freshservice` - freshservice\n\* `front` - front\n\* `gorgias` - gorgias\n\* `kustomer` - kustomer\n\* `dixa` - dixa\n\* `plain` - plain\n\* `gitlab` - gitlab\n\* `gitea` - gitea\n\* `shortcut` - shortcut\n\* `sentry` - sentry\n\* `rollbar` - rollbar\n\* `bugsnag` - bugsnag\n\* `honeybadger` - honeybadger\n\* `raygun` - raygun\n\* `snyk` - snyk\n\* `sonarqube` - sonarqube\n\* `semgrep` - semgrep\n\* `rapid7_insightvm` - rapid7_insightvm\n\* `featurebase` - featurebase\n\* `frill` - frill\n\* `aha` - aha\n\* `uservoice` - uservoice\n\* `productboard` - productboard\n\* `canny` - canny\n\* `asknicely` - asknicely\n\* `retently` - retently\n\* `appfigures` - appfigures\n\* `appfollow` - appfollow\n\* `judgeme_reviews` - judgeme_reviews\n\* `intercom` - intercom\n\* `hubspot` - hubspot\n\* `engineering_analytics` - engineering_analytics\n\* `google_search_console` - google_search_console'
    )

export type SignalSourceProductApi = zod.input<typeof SignalSourceProductApi>
export type SignalSourceProductApiOutput = zod.output<typeof SignalSourceProductApi>

export const SignalSourceTypeApi = zod
    .enum([
        'session_analysis_cluster',
        'session_problem',
        'evaluation',
        'evaluation_report',
        'issue',
        'ticket',
        'issue_created',
        'issue_reopened',
        'issue_spiking',
        'endpoint_execution_failed',
        'endpoint_breakdown_limit_exceeded',
        'cross_source_issue',
        'alert_state_change',
        'health_issue',
        'scanner_finding',
        'anomaly_investigation',
        'feedback',
        'review',
        'ci_flaky_check',
        'ci_broken_default_branch',
        'ci_duration_regression',
        'search_opportunity',
    ])
    .describe(
        '\* `session_analysis_cluster` - session_analysis_cluster\n\* `session_problem` - session_problem\n\* `evaluation` - evaluation\n\* `evaluation_report` - evaluation_report\n\* `issue` - issue\n\* `ticket` - ticket\n\* `issue_created` - issue_created\n\* `issue_reopened` - issue_reopened\n\* `issue_spiking` - issue_spiking\n\* `endpoint_execution_failed` - endpoint_execution_failed\n\* `endpoint_breakdown_limit_exceeded` - endpoint_breakdown_limit_exceeded\n\* `cross_source_issue` - cross_source_issue\n\* `alert_state_change` - alert_state_change\n\* `health_issue` - health_issue\n\* `scanner_finding` - scanner_finding\n\* `anomaly_investigation` - anomaly_investigation\n\* `feedback` - feedback\n\* `review` - review\n\* `ci_flaky_check` - ci_flaky_check\n\* `ci_broken_default_branch` - ci_broken_default_branch\n\* `ci_duration_regression` - ci_duration_regression\n\* `search_opportunity` - search_opportunity'
    )

export type SignalSourceTypeApi = zod.input<typeof SignalSourceTypeApi>
export type SignalSourceTypeApiOutput = zod.output<typeof SignalSourceTypeApi>

export const SignalExtraApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type SignalExtraApi = zod.input<typeof SignalExtraApi>
export type SignalExtraApiOutput = zod.output<typeof SignalExtraApi>

export const SpecificityMetadataApi = zod.object({
    pr_title: zod.string().describe('Title of the PR the specificity gate evaluated.'),
    specific_enough: zod.boolean().describe('Whether the report passed the PR-specificity gate.'),
    reason: zod.string().describe("The gate's reasoning."),
})

export type SpecificityMetadataApi = zod.input<typeof SpecificityMetadataApi>
export type SpecificityMetadataApiOutput = zod.output<typeof SpecificityMetadataApi>

export const MatchedMetadataApi = zod.object({
    parent_signal_id: zod.string().describe('Signal already in the report that this one matched.'),
    match_query: zod.string().describe('Query used to find the parent signal.'),
    reason: zod.string().describe('Why the signals were judged to describe the same issue.'),
    specificity: zod
        .union([SpecificityMetadataApi, zod.null()])
        .optional()
        .describe('PR-specificity gate result, when the gate ran.'),
})

export type MatchedMetadataApi = zod.input<typeof MatchedMetadataApi>
export type MatchedMetadataApiOutput = zod.output<typeof MatchedMetadataApi>

export const NoMatchMetadataApi = zod.object({
    reason: zod.string().describe('Why no existing report matched.'),
    rejected_signal_ids: zod.array(zod.string()).describe('Candidate signals that were considered and rejected.'),
    specificity_rejection: zod
        .union([SpecificityMetadataApi, zod.null()])
        .optional()
        .describe('PR-specificity gate result that caused a rejection, when present.'),
})

export type NoMatchMetadataApi = zod.input<typeof NoMatchMetadataApi>
export type NoMatchMetadataApiOutput = zod.output<typeof NoMatchMetadataApi>

export const SignalMatchMetadataApi = zod.union([MatchedMetadataApi, NoMatchMetadataApi])

export type SignalMatchMetadataApi = zod.input<typeof SignalMatchMetadataApi>
export type SignalMatchMetadataApiOutput = zod.output<typeof SignalMatchMetadataApi>

export const ProblemTypeEnumApi = zod.enum([
    'confusion',
    'abandonment',
    'blocking_exception',
    'non_blocking_exception',
    'failure',
])

export type ProblemTypeEnumApi = zod.input<typeof ProblemTypeEnumApi>
export type ProblemTypeEnumApiOutput = zod.output<typeof ProblemTypeEnumApi>

export const SessionProblemEventEntryApi = zod.object({
    event: zod.string(),
    timestamp: zod.string(),
    current_url: zod.union([zod.string(), zod.null()]).optional(),
    event_type: zod.union([zod.string(), zod.null()]).optional(),
    interaction_text: zod.union([zod.string(), zod.null()]).optional(),
})

export type SessionProblemEventEntryApi = zod.input<typeof SessionProblemEventEntryApi>
export type SessionProblemEventEntryApiOutput = zod.output<typeof SessionProblemEventEntryApi>

export const SessionProblemSignalExtraApi = zod.object({
    session_id: zod.string(),
    segment_title: zod.string(),
    start_time: zod.string(),
    end_time: zod.string(),
    problem_type: ProblemTypeEnumApi,
    distinct_id: zod.string(),
    session_start_time: zod.union([zod.string(), zod.null()]).optional(),
    session_end_time: zod.union([zod.string(), zod.null()]).optional(),
    session_duration: zod.union([zod.number(), zod.null()]).optional(),
    session_active_seconds: zod.union([zod.number(), zod.null()]).optional(),
    exported_asset_id: zod.union([zod.number(), zod.null()]).optional(),
    event_history: zod.union([zod.array(SessionProblemEventEntryApi), zod.null()]).optional(),
})

export type SessionProblemSignalExtraApi = zod.input<typeof SessionProblemSignalExtraApi>
export type SessionProblemSignalExtraApiOutput = zod.output<typeof SessionProblemSignalExtraApi>

export const LlmEvalSignalExtraApi = zod.object({
    evaluation_id: zod.string(),
    target_event_id: zod.union([zod.string(), zod.null()]).optional(),
    target_event_type: zod.union([zod.string(), zod.null()]).optional(),
    trace_id: zod.string(),
    model: zod.union([zod.string(), zod.null()]).optional(),
    provider: zod.union([zod.string(), zod.null()]).optional(),
})

export type LlmEvalSignalExtraApi = zod.input<typeof LlmEvalSignalExtraApi>
export type LlmEvalSignalExtraApiOutput = zod.output<typeof LlmEvalSignalExtraApi>

export const LlmEvalReportSignalExtraApi = zod.object({
    evaluation_id: zod.string(),
    evaluation_name: zod.string(),
    evaluation_description: zod.string(),
    report_id: zod.string(),
    report_run_id: zod.string(),
    period_start: zod.string(),
    period_end: zod.string(),
})

export type LlmEvalReportSignalExtraApi = zod.input<typeof LlmEvalReportSignalExtraApi>
export type LlmEvalReportSignalExtraApiOutput = zod.output<typeof LlmEvalReportSignalExtraApi>

export const ZendeskTicketSignalExtraApi = zod.object({
    url: zod.string(),
    type: zod.union([zod.string(), zod.null()]),
    tags: zod.array(zod.string()),
    created_at: zod.string(),
    priority: zod.union([zod.string(), zod.null()]),
    status: zod.string(),
})

export type ZendeskTicketSignalExtraApi = zod.input<typeof ZendeskTicketSignalExtraApi>
export type ZendeskTicketSignalExtraApiOutput = zod.output<typeof ZendeskTicketSignalExtraApi>

export const GithubIssueSignalExtraApi = zod.object({
    html_url: zod.string(),
    number: zod.number(),
    labels: zod.array(zod.string()),
    created_at: zod.string(),
    updated_at: zod.string(),
    locked: zod.boolean(),
    state: zod.string(),
})

export type GithubIssueSignalExtraApi = zod.input<typeof GithubIssueSignalExtraApi>
export type GithubIssueSignalExtraApiOutput = zod.output<typeof GithubIssueSignalExtraApi>

export const LinearIssueSignalExtraApi = zod.object({
    url: zod.string(),
    identifier: zod.string(),
    number: zod.number(),
    priority: zod.number(),
    priority_label: zod.string(),
    labels: zod.array(zod.string()),
    state_name: zod.union([zod.string(), zod.null()]),
    state_type: zod.union([zod.string(), zod.null()]),
    team_name: zod.union([zod.string(), zod.null()]),
    created_at: zod.string(),
    updated_at: zod.string(),
})

export type LinearIssueSignalExtraApi = zod.input<typeof LinearIssueSignalExtraApi>
export type LinearIssueSignalExtraApiOutput = zod.output<typeof LinearIssueSignalExtraApi>

export const JiraIssueSignalExtraApi = zod.object({
    key: zod.string(),
    url: zod.union([zod.string(), zod.null()]),
    status: zod.union([zod.string(), zod.null()]),
    priority: zod.union([zod.string(), zod.null()]),
    assignee: zod.union([zod.string(), zod.null()]),
    labels: zod.array(zod.string()),
    created: zod.union([zod.string(), zod.null()]),
    updated: zod.union([zod.string(), zod.null()]),
})

export type JiraIssueSignalExtraApi = zod.input<typeof JiraIssueSignalExtraApi>
export type JiraIssueSignalExtraApiOutput = zod.output<typeof JiraIssueSignalExtraApi>

export const ConversationsTicketImageApi = zod.object({
    url: zod.string(),
    author: zod.string(),
})

export type ConversationsTicketImageApi = zod.input<typeof ConversationsTicketImageApi>
export type ConversationsTicketImageApiOutput = zod.output<typeof ConversationsTicketImageApi>

export const ConversationsTicketSignalExtraApi = zod.object({
    ticket_number: zod.number(),
    channel_source: zod.string(),
    channel_detail: zod.union([zod.string(), zod.null()]),
    status: zod.string(),
    priority: zod.union([zod.string(), zod.null()]),
    created_at: zod.string(),
    email_subject: zod.union([zod.string(), zod.null()]),
    images: zod.union([zod.array(ConversationsTicketImageApi), zod.null()]).optional(),
})

export type ConversationsTicketSignalExtraApi = zod.input<typeof ConversationsTicketSignalExtraApi>
export type ConversationsTicketSignalExtraApiOutput = zod.output<typeof ConversationsTicketSignalExtraApi>

export const ErrorTrackingSignalExtraApi = zod.object({
    fingerprint: zod.string(),
})

export type ErrorTrackingSignalExtraApi = zod.input<typeof ErrorTrackingSignalExtraApi>
export type ErrorTrackingSignalExtraApiOutput = zod.output<typeof ErrorTrackingSignalExtraApi>

export const PgAnalyzeIssueReferenceApi = zod.object({
    kind: zod.union([zod.string(), zod.null()]).optional(),
    name: zod.union([zod.string(), zod.null()]).optional(),
    url: zod.union([zod.string(), zod.null()]).optional(),
    queryText: zod.union([zod.string(), zod.null()]).optional(),
})

export type PgAnalyzeIssueReferenceApi = zod.input<typeof PgAnalyzeIssueReferenceApi>
export type PgAnalyzeIssueReferenceApiOutput = zod.output<typeof PgAnalyzeIssueReferenceApi>

export const PgAnalyzeIssueSignalExtraApi = zod.object({
    severity: zod.union([zod.string(), zod.null()]),
    references: zod.array(PgAnalyzeIssueReferenceApi),
    database_id: zod.union([zod.string(), zod.null()]),
    server_human_id: zod.union([zod.string(), zod.null()]),
    server_name: zod.union([zod.string(), zod.null()]),
    synced_at: zod.string(),
})

export type PgAnalyzeIssueSignalExtraApi = zod.input<typeof PgAnalyzeIssueSignalExtraApi>
export type PgAnalyzeIssueSignalExtraApiOutput = zod.output<typeof PgAnalyzeIssueSignalExtraApi>

export const EndpointExecutionFailedSignalExtraApi = zod.object({
    endpoint_name: zod.string(),
    endpoint_version: zod.union([zod.number(), zod.null()]),
    materialized: zod.boolean(),
    saved_query_id: zod.union([zod.string(), zod.null()]),
    error_class: zod.string(),
    error_message: zod.string(),
})

export type EndpointExecutionFailedSignalExtraApi = zod.input<typeof EndpointExecutionFailedSignalExtraApi>
export type EndpointExecutionFailedSignalExtraApiOutput = zod.output<typeof EndpointExecutionFailedSignalExtraApi>

export const EndpointBreakdownLimitExceededSignalExtraApi = zod.object({
    endpoint_name: zod.string(),
    breakdown_limit: zod.number(),
})

export type EndpointBreakdownLimitExceededSignalExtraApi = zod.input<
    typeof EndpointBreakdownLimitExceededSignalExtraApi
>
export type EndpointBreakdownLimitExceededSignalExtraApiOutput = zod.output<
    typeof EndpointBreakdownLimitExceededSignalExtraApi
>

export const ReportPriorityApi = zod.enum(['P0', 'P1', 'P2', 'P3', 'P4'])

export type ReportPriorityApi = zod.input<typeof ReportPriorityApi>
export type ReportPriorityApiOutput = zod.output<typeof ReportPriorityApi>

export const SignalsScoutEvidenceEntryApi = zod.object({
    source_product: zod.string(),
    entity_id: zod.union([zod.string(), zod.null()]).optional(),
    summary: zod.string(),
})

export type SignalsScoutEvidenceEntryApi = zod.input<typeof SignalsScoutEvidenceEntryApi>
export type SignalsScoutEvidenceEntryApiOutput = zod.output<typeof SignalsScoutEvidenceEntryApi>

export const SignalsScoutTimeRangeApi = zod.object({
    date_from: zod.string(),
    date_to: zod.string(),
})

export type SignalsScoutTimeRangeApi = zod.input<typeof SignalsScoutTimeRangeApi>
export type SignalsScoutTimeRangeApiOutput = zod.output<typeof SignalsScoutTimeRangeApi>

export const SignalsScoutSignalExtraApi = zod.object({
    scout_run_id: zod.string(),
    task_run_id: zod.string(),
    task_id: zod.union([zod.string(), zod.null()]).optional(),
    finding_id: zod.string(),
    skill_name: zod.string(),
    skill_version: zod.number(),
    confidence: zod.number(),
    severity: zod.union([ReportPriorityApi, zod.null()]).optional(),
    hypothesis: zod.union([zod.string(), zod.null()]).optional(),
    evidence: zod.array(SignalsScoutEvidenceEntryApi),
    dedupe_keys: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    tags: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    time_range: zod.union([SignalsScoutTimeRangeApi, zod.null()]).optional(),
    mcp_trace_id: zod.union([zod.string(), zod.null()]).optional(),
})

export type SignalsScoutSignalExtraApi = zod.input<typeof SignalsScoutSignalExtraApi>
export type SignalsScoutSignalExtraApiOutput = zod.output<typeof SignalsScoutSignalExtraApi>

export const LogsAlertStateChangeSignalExtraActionEnumApi = zod.enum(['firing', 'broken'])

export type LogsAlertStateChangeSignalExtraActionEnumApi = zod.input<
    typeof LogsAlertStateChangeSignalExtraActionEnumApi
>
export type LogsAlertStateChangeSignalExtraActionEnumApiOutput = zod.output<
    typeof LogsAlertStateChangeSignalExtraActionEnumApi
>

export const LogsAlertStateChangeSignalExtraThresholdOperatorEnumApi = zod.enum(['above', 'below'])

export type LogsAlertStateChangeSignalExtraThresholdOperatorEnumApi = zod.input<
    typeof LogsAlertStateChangeSignalExtraThresholdOperatorEnumApi
>
export type LogsAlertStateChangeSignalExtraThresholdOperatorEnumApiOutput = zod.output<
    typeof LogsAlertStateChangeSignalExtraThresholdOperatorEnumApi
>

export const LogsAlertStateChangeSignalExtraApi = zod.object({
    alert_id: zod.string(),
    alert_name: zod.string(),
    action: LogsAlertStateChangeSignalExtraActionEnumApi,
    threshold_count: zod.number(),
    threshold_operator: LogsAlertStateChangeSignalExtraThresholdOperatorEnumApi,
    window_minutes: zod.number(),
    result_count: zod.union([zod.number(), zod.null()]),
    consecutive_failures: zod.number(),
    filters: zod.record(zod.string(), zod.unknown()),
    url: zod.string(),
})

export type LogsAlertStateChangeSignalExtraApi = zod.input<typeof LogsAlertStateChangeSignalExtraApi>
export type LogsAlertStateChangeSignalExtraApiOutput = zod.output<typeof LogsAlertStateChangeSignalExtraApi>

export const ReplayVisionScannerFindingSignalExtraApi = zod.object({
    scanner_id: zod.string(),
    scanner_name: zod.string(),
    scanner_type: zod.string(),
    observation_id: zod.string(),
    session_id: zod.string(),
    confidence: zod.number(),
    problem_type: zod.string(),
    start_time: zod.number(),
    end_time: zod.number(),
    url: zod.string(),
    exported_asset_id: zod.number(),
    distinct_id: zod.union([zod.string(), zod.null()]).optional(),
    recording_start_time: zod.union([zod.string(), zod.null()]).optional(),
    recording_end_time: zod.union([zod.string(), zod.null()]).optional(),
    recording_duration: zod.union([zod.number(), zod.null()]).optional(),
    recording_active_seconds: zod.union([zod.number(), zod.null()]).optional(),
})

export type ReplayVisionScannerFindingSignalExtraApi = zod.input<typeof ReplayVisionScannerFindingSignalExtraApi>
export type ReplayVisionScannerFindingSignalExtraApiOutput = zod.output<typeof ReplayVisionScannerFindingSignalExtraApi>

export const InvestigationVerdictEnumApi = zod
    .enum(['true_positive', 'false_positive', 'inconclusive'])
    .describe(
        '\* `true_positive` - true_positive\n\* `false_positive` - false_positive\n\* `inconclusive` - inconclusive'
    )

export type InvestigationVerdictEnumApi = zod.input<typeof InvestigationVerdictEnumApi>
export type InvestigationVerdictEnumApiOutput = zod.output<typeof InvestigationVerdictEnumApi>

export const AnalyticsAnomalyInvestigationSignalExtraApi = zod.object({
    alert_id: zod.string(),
    alert_name: zod.string(),
    alert_check_id: zod.string(),
    insight_id: zod.string(),
    detector_type: zod.string(),
    verdict: InvestigationVerdictEnumApi,
    url: zod.string(),
    insight_name: zod.union([zod.string(), zod.null()]).optional(),
    insight_short_id: zod.union([zod.string(), zod.null()]).optional(),
    triggered_dates: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    notebook_short_id: zod.union([zod.string(), zod.null()]).optional(),
})

export type AnalyticsAnomalyInvestigationSignalExtraApi = zod.input<typeof AnalyticsAnomalyInvestigationSignalExtraApi>
export type AnalyticsAnomalyInvestigationSignalExtraApiOutput = zod.output<
    typeof AnalyticsAnomalyInvestigationSignalExtraApi
>

export const HealthCheckSignalExtraSeverityEnumApi = zod.enum(['critical', 'warning', 'info'])

export type HealthCheckSignalExtraSeverityEnumApi = zod.input<typeof HealthCheckSignalExtraSeverityEnumApi>
export type HealthCheckSignalExtraSeverityEnumApiOutput = zod.output<typeof HealthCheckSignalExtraSeverityEnumApi>

export const HealthCheckSignalExtraApi = zod.object({
    kind: zod.string(),
    severity: HealthCheckSignalExtraSeverityEnumApi,
    issue_id: zod.string(),
    title: zod.string(),
    summary: zod.string(),
    link: zod.string(),
    url: zod.string(),
    payload: zod.record(zod.string(), zod.unknown()),
})

export type HealthCheckSignalExtraApi = zod.input<typeof HealthCheckSignalExtraApi>
export type HealthCheckSignalExtraApiOutput = zod.output<typeof HealthCheckSignalExtraApi>

export const EngineeringAnalyticsCIFlakyCheckSignalExtraApi = zod
    .object({
        repo_owner: zod.string(),
        repo_name: zod.string(),
        workflow_name: zod.string(),
        job_name: zod.string(),
        run_id: zod.number(),
        head_sha: zod.string(),
        failed_attempt: zod.number(),
        passed_attempt: zod.number(),
        flaky_count: zod.number(),
        window_days: zod.number(),
    })
    .describe(
        'One immutable flaky observation: failed then passed on a later attempt of the same run,\nso only non-determinism can explain the flip.'
    )

export type EngineeringAnalyticsCIFlakyCheckSignalExtraApi = zod.input<
    typeof EngineeringAnalyticsCIFlakyCheckSignalExtraApi
>
export type EngineeringAnalyticsCIFlakyCheckSignalExtraApiOutput = zod.output<
    typeof EngineeringAnalyticsCIFlakyCheckSignalExtraApi
>

export const EngineeringAnalyticsCIBrokenDefaultBranchSignalExtraApi = zod.object({
    repo_owner: zod.string(),
    repo_name: zod.string(),
    workflow_name: zod.string(),
    branch: zod.string(),
    conclusive_success_rate: zod.number(),
    conclusive_run_count: zod.number(),
    latest_conclusion: zod.string(),
    window_hours: zod.number(),
})

export type EngineeringAnalyticsCIBrokenDefaultBranchSignalExtraApi = zod.input<
    typeof EngineeringAnalyticsCIBrokenDefaultBranchSignalExtraApi
>
export type EngineeringAnalyticsCIBrokenDefaultBranchSignalExtraApiOutput = zod.output<
    typeof EngineeringAnalyticsCIBrokenDefaultBranchSignalExtraApi
>

export const EngineeringAnalyticsCIDurationRegressionSignalExtraApi = zod.object({
    repo_owner: zod.string(),
    repo_name: zod.string(),
    workflow_name: zod.string(),
    current_p95_seconds: zod.number(),
    baseline_p95_seconds: zod.number(),
    pct_increase: zod.number(),
    current_p50_seconds: zod.number(),
    baseline_p50_seconds: zod.number(),
    window_days: zod.number(),
})

export type EngineeringAnalyticsCIDurationRegressionSignalExtraApi = zod.input<
    typeof EngineeringAnalyticsCIDurationRegressionSignalExtraApi
>
export type EngineeringAnalyticsCIDurationRegressionSignalExtraApiOutput = zod.output<
    typeof EngineeringAnalyticsCIDurationRegressionSignalExtraApi
>

export const FreshdeskTicketSignalExtraApi = zod.object({
    status: zod.union([zod.string(), zod.null()]),
    priority: zod.union([zod.string(), zod.null()]),
    type: zod.union([zod.string(), zod.null()]),
    tags: zod.array(zod.unknown()),
    created_at: zod.union([zod.string(), zod.null()]),
})

export type FreshdeskTicketSignalExtraApi = zod.input<typeof FreshdeskTicketSignalExtraApi>
export type FreshdeskTicketSignalExtraApiOutput = zod.output<typeof FreshdeskTicketSignalExtraApi>

export const FreshserviceTicketSignalExtraApi = zod.object({
    status: zod.union([zod.string(), zod.null()]),
    priority: zod.union([zod.string(), zod.null()]),
    type: zod.union([zod.string(), zod.null()]),
    category: zod.union([zod.string(), zod.null()]),
    tags: zod.array(zod.unknown()),
    created_at: zod.union([zod.string(), zod.null()]),
})

export type FreshserviceTicketSignalExtraApi = zod.input<typeof FreshserviceTicketSignalExtraApi>
export type FreshserviceTicketSignalExtraApiOutput = zod.output<typeof FreshserviceTicketSignalExtraApi>

export const FrontConversationSignalExtraApi = zod.object({
    status: zod.union([zod.string(), zod.null()]),
    tags: zod.array(zod.unknown()),
    created_at: zod.union([zod.string(), zod.null()]),
})

export type FrontConversationSignalExtraApi = zod.input<typeof FrontConversationSignalExtraApi>
export type FrontConversationSignalExtraApiOutput = zod.output<typeof FrontConversationSignalExtraApi>

export const GorgiasTicketSignalExtraApi = zod.object({
    status: zod.union([zod.string(), zod.null()]),
    priority: zod.union([zod.string(), zod.null()]),
    channel: zod.union([zod.string(), zod.null()]),
    tags: zod.array(zod.unknown()),
    created_datetime: zod.union([zod.string(), zod.null()]),
})

export type GorgiasTicketSignalExtraApi = zod.input<typeof GorgiasTicketSignalExtraApi>
export type GorgiasTicketSignalExtraApiOutput = zod.output<typeof GorgiasTicketSignalExtraApi>

export const KustomerConversationSignalExtraApi = zod.object({
    status: zod.union([zod.string(), zod.null()]),
    priority: zod.union([zod.string(), zod.null()]),
    tags: zod.array(zod.unknown()),
    createdAt: zod.union([zod.string(), zod.null()]),
})

export type KustomerConversationSignalExtraApi = zod.input<typeof KustomerConversationSignalExtraApi>
export type KustomerConversationSignalExtraApiOutput = zod.output<typeof KustomerConversationSignalExtraApi>

export const DixaConversationSignalExtraApi = zod.object({
    status: zod.union([zod.string(), zod.null()]),
    channel: zod.union([zod.string(), zod.null()]),
    tags: zod.array(zod.unknown()),
    created_at: zod.union([zod.string(), zod.null()]),
})

export type DixaConversationSignalExtraApi = zod.input<typeof DixaConversationSignalExtraApi>
export type DixaConversationSignalExtraApiOutput = zod.output<typeof DixaConversationSignalExtraApi>

export const PlainThreadSignalExtraApi = zod.object({
    status: zod.union([zod.string(), zod.null()]),
    priority: zod.union([zod.string(), zod.null()]),
    labels: zod.array(zod.unknown()),
    createdAt: zod.union([zod.string(), zod.null()]),
})

export type PlainThreadSignalExtraApi = zod.input<typeof PlainThreadSignalExtraApi>
export type PlainThreadSignalExtraApiOutput = zod.output<typeof PlainThreadSignalExtraApi>

export const GitlabIssueSignalExtraApi = zod.object({
    state: zod.union([zod.string(), zod.null()]),
    labels: zod.array(zod.unknown()),
    iid: zod.union([zod.string(), zod.null()]),
    project_id: zod.union([zod.string(), zod.null()]),
    created_at: zod.union([zod.string(), zod.null()]),
})

export type GitlabIssueSignalExtraApi = zod.input<typeof GitlabIssueSignalExtraApi>
export type GitlabIssueSignalExtraApiOutput = zod.output<typeof GitlabIssueSignalExtraApi>

export const GiteaIssueSignalExtraApi = zod.object({
    state: zod.union([zod.string(), zod.null()]),
    labels: zod.array(zod.unknown()),
    html_url: zod.union([zod.string(), zod.null()]),
    number: zod.union([zod.string(), zod.null()]),
    created_at: zod.union([zod.string(), zod.null()]),
})

export type GiteaIssueSignalExtraApi = zod.input<typeof GiteaIssueSignalExtraApi>
export type GiteaIssueSignalExtraApiOutput = zod.output<typeof GiteaIssueSignalExtraApi>

export const ShortcutStorySignalExtraApi = zod.object({
    story_type: zod.union([zod.string(), zod.null()]),
    labels: zod.array(zod.unknown()),
    workflow_state_id: zod.union([zod.string(), zod.null()]),
    created_at: zod.union([zod.string(), zod.null()]),
})

export type ShortcutStorySignalExtraApi = zod.input<typeof ShortcutStorySignalExtraApi>
export type ShortcutStorySignalExtraApiOutput = zod.output<typeof ShortcutStorySignalExtraApi>

export const SentryIssueSignalExtraApi = zod.object({
    level: zod.union([zod.string(), zod.null()]),
    status: zod.union([zod.string(), zod.null()]),
    permalink: zod.union([zod.string(), zod.null()]),
    shortId: zod.union([zod.string(), zod.null()]),
    firstSeen: zod.union([zod.string(), zod.null()]),
})

export type SentryIssueSignalExtraApi = zod.input<typeof SentryIssueSignalExtraApi>
export type SentryIssueSignalExtraApiOutput = zod.output<typeof SentryIssueSignalExtraApi>

export const RollbarItemSignalExtraApi = zod.object({
    level: zod.union([zod.string(), zod.null()]),
    status: zod.union([zod.string(), zod.null()]),
    environment: zod.union([zod.string(), zod.null()]),
    framework: zod.union([zod.string(), zod.null()]),
    last_occurrence_timestamp: zod.union([zod.string(), zod.null()]),
})

export type RollbarItemSignalExtraApi = zod.input<typeof RollbarItemSignalExtraApi>
export type RollbarItemSignalExtraApiOutput = zod.output<typeof RollbarItemSignalExtraApi>

export const BugsnagErrorSignalExtraApi = zod.object({
    severity: zod.union([zod.string(), zod.null()]),
    status: zod.union([zod.string(), zod.null()]),
    context: zod.union([zod.string(), zod.null()]),
    first_seen: zod.union([zod.string(), zod.null()]),
    last_seen: zod.union([zod.string(), zod.null()]),
})

export type BugsnagErrorSignalExtraApi = zod.input<typeof BugsnagErrorSignalExtraApi>
export type BugsnagErrorSignalExtraApiOutput = zod.output<typeof BugsnagErrorSignalExtraApi>

export const HoneybadgerFaultSignalExtraApi = zod.object({
    environment: zod.union([zod.string(), zod.null()]),
    component: zod.union([zod.string(), zod.null()]),
    action: zod.union([zod.string(), zod.null()]),
    tags: zod.array(zod.unknown()),
    url: zod.union([zod.string(), zod.null()]),
    created_at: zod.union([zod.string(), zod.null()]),
})

export type HoneybadgerFaultSignalExtraApi = zod.input<typeof HoneybadgerFaultSignalExtraApi>
export type HoneybadgerFaultSignalExtraApiOutput = zod.output<typeof HoneybadgerFaultSignalExtraApi>

export const RaygunErrorGroupSignalExtraApi = zod.object({
    status: zod.union([zod.string(), zod.null()]),
    applicationUrl: zod.union([zod.string(), zod.null()]),
    lastOccurredAt: zod.union([zod.string(), zod.null()]),
    createdAt: zod.union([zod.string(), zod.null()]),
})

export type RaygunErrorGroupSignalExtraApi = zod.input<typeof RaygunErrorGroupSignalExtraApi>
export type RaygunErrorGroupSignalExtraApiOutput = zod.output<typeof RaygunErrorGroupSignalExtraApi>

export const SnykScannerFindingSignalExtraApi = zod.object({
    effective_severity_level: zod.union([zod.string(), zod.null()]),
    status: zod.union([zod.string(), zod.null()]),
    type: zod.union([zod.string(), zod.null()]),
    created_at: zod.union([zod.string(), zod.null()]),
})

export type SnykScannerFindingSignalExtraApi = zod.input<typeof SnykScannerFindingSignalExtraApi>
export type SnykScannerFindingSignalExtraApiOutput = zod.output<typeof SnykScannerFindingSignalExtraApi>

export const SonarqubeScannerFindingSignalExtraApi = zod.object({
    severity: zod.union([zod.string(), zod.null()]),
    type: zod.union([zod.string(), zod.null()]),
    status: zod.union([zod.string(), zod.null()]),
    component: zod.union([zod.string(), zod.null()]),
    rule: zod.union([zod.string(), zod.null()]),
    creationDate: zod.union([zod.string(), zod.null()]),
})

export type SonarqubeScannerFindingSignalExtraApi = zod.input<typeof SonarqubeScannerFindingSignalExtraApi>
export type SonarqubeScannerFindingSignalExtraApiOutput = zod.output<typeof SonarqubeScannerFindingSignalExtraApi>

export const SemgrepScannerFindingSignalExtraApi = zod.object({
    severity: zod.union([zod.string(), zod.null()]),
    confidence: zod.union([zod.string(), zod.null()]),
    status: zod.union([zod.string(), zod.null()]),
    state: zod.union([zod.string(), zod.null()]),
    created_at: zod.union([zod.string(), zod.null()]),
})

export type SemgrepScannerFindingSignalExtraApi = zod.input<typeof SemgrepScannerFindingSignalExtraApi>
export type SemgrepScannerFindingSignalExtraApiOutput = zod.output<typeof SemgrepScannerFindingSignalExtraApi>

export const Rapid7InsightvmScannerFindingSignalExtraApi = zod.object({
    severity: zod.union([zod.string(), zod.null()]),
    cvss_v3_score: zod.union([zod.string(), zod.null()]),
    published: zod.union([zod.string(), zod.null()]),
    added: zod.union([zod.string(), zod.null()]),
})

export type Rapid7InsightvmScannerFindingSignalExtraApi = zod.input<typeof Rapid7InsightvmScannerFindingSignalExtraApi>
export type Rapid7InsightvmScannerFindingSignalExtraApiOutput = zod.output<
    typeof Rapid7InsightvmScannerFindingSignalExtraApi
>

export const FeaturebaseFeedbackSignalExtraApi = zod.object({
    status: zod.union([zod.string(), zod.null()]),
    tags: zod.array(zod.unknown()),
    upvotes: zod.union([zod.string(), zod.null()]),
    createdAt: zod.union([zod.string(), zod.null()]),
})

export type FeaturebaseFeedbackSignalExtraApi = zod.input<typeof FeaturebaseFeedbackSignalExtraApi>
export type FeaturebaseFeedbackSignalExtraApiOutput = zod.output<typeof FeaturebaseFeedbackSignalExtraApi>

export const FrillFeedbackSignalExtraApi = zod.object({
    status: zod.union([zod.string(), zod.null()]),
    vote_count: zod.union([zod.string(), zod.null()]),
    topics: zod.array(zod.unknown()),
    created_at: zod.union([zod.string(), zod.null()]),
})

export type FrillFeedbackSignalExtraApi = zod.input<typeof FrillFeedbackSignalExtraApi>
export type FrillFeedbackSignalExtraApiOutput = zod.output<typeof FrillFeedbackSignalExtraApi>

export const AhaFeedbackSignalExtraApi = zod.object({
    workflow_status: zod.union([zod.string(), zod.null()]),
    score: zod.union([zod.string(), zod.null()]),
    votes: zod.union([zod.string(), zod.null()]),
    url: zod.union([zod.string(), zod.null()]),
    created_at: zod.union([zod.string(), zod.null()]),
})

export type AhaFeedbackSignalExtraApi = zod.input<typeof AhaFeedbackSignalExtraApi>
export type AhaFeedbackSignalExtraApiOutput = zod.output<typeof AhaFeedbackSignalExtraApi>

export const UservoiceFeedbackSignalExtraApi = zod.object({
    state: zod.union([zod.string(), zod.null()]),
    vote_count: zod.union([zod.string(), zod.null()]),
    category_name: zod.union([zod.string(), zod.null()]),
    created_at: zod.union([zod.string(), zod.null()]),
})

export type UservoiceFeedbackSignalExtraApi = zod.input<typeof UservoiceFeedbackSignalExtraApi>
export type UservoiceFeedbackSignalExtraApiOutput = zod.output<typeof UservoiceFeedbackSignalExtraApi>

export const ProductboardFeedbackSignalExtraApi = zod.object({
    state: zod.union([zod.string(), zod.null()]),
    tags: zod.array(zod.unknown()),
    displayUrl: zod.union([zod.string(), zod.null()]),
    createdAt: zod.union([zod.string(), zod.null()]),
})

export type ProductboardFeedbackSignalExtraApi = zod.input<typeof ProductboardFeedbackSignalExtraApi>
export type ProductboardFeedbackSignalExtraApiOutput = zod.output<typeof ProductboardFeedbackSignalExtraApi>

export const CannyFeedbackSignalExtraApi = zod.object({
    status: zod.union([zod.string(), zod.null()]),
    tags: zod.array(zod.unknown()),
    score: zod.union([zod.string(), zod.null()]),
    voteCount: zod.union([zod.string(), zod.null()]),
    url: zod.union([zod.string(), zod.null()]),
    created: zod.union([zod.string(), zod.null()]),
})

export type CannyFeedbackSignalExtraApi = zod.input<typeof CannyFeedbackSignalExtraApi>
export type CannyFeedbackSignalExtraApiOutput = zod.output<typeof CannyFeedbackSignalExtraApi>

export const AsknicelyFeedbackSignalExtraApi = zod.object({
    score: zod.union([zod.string(), zod.null()]),
    status: zod.union([zod.string(), zod.null()]),
    question_type: zod.union([zod.string(), zod.null()]),
    segment: zod.union([zod.string(), zod.null()]),
    created: zod.union([zod.string(), zod.null()]),
})

export type AsknicelyFeedbackSignalExtraApi = zod.input<typeof AsknicelyFeedbackSignalExtraApi>
export type AsknicelyFeedbackSignalExtraApiOutput = zod.output<typeof AsknicelyFeedbackSignalExtraApi>

export const RetentlyFeedbackSignalExtraApi = zod.object({
    score: zod.union([zod.string(), zod.null()]),
    ratingCategory: zod.union([zod.string(), zod.null()]),
    feedbackTopics: zod.array(zod.unknown()),
    resolved: zod.union([zod.string(), zod.null()]),
    createdDate: zod.union([zod.string(), zod.null()]),
})

export type RetentlyFeedbackSignalExtraApi = zod.input<typeof RetentlyFeedbackSignalExtraApi>
export type RetentlyFeedbackSignalExtraApiOutput = zod.output<typeof RetentlyFeedbackSignalExtraApi>

export const AppfiguresReviewSignalExtraApi = zod.object({
    stars: zod.union([zod.string(), zod.null()]),
    version: zod.union([zod.string(), zod.null()]),
    product: zod.union([zod.string(), zod.null()]),
    date: zod.union([zod.string(), zod.null()]),
})

export type AppfiguresReviewSignalExtraApi = zod.input<typeof AppfiguresReviewSignalExtraApi>
export type AppfiguresReviewSignalExtraApiOutput = zod.output<typeof AppfiguresReviewSignalExtraApi>

export const AppfollowReviewSignalExtraApi = zod.object({
    rating: zod.union([zod.string(), zod.null()]),
    store: zod.union([zod.string(), zod.null()]),
    app_version: zod.union([zod.string(), zod.null()]),
    date: zod.union([zod.string(), zod.null()]),
})

export type AppfollowReviewSignalExtraApi = zod.input<typeof AppfollowReviewSignalExtraApi>
export type AppfollowReviewSignalExtraApiOutput = zod.output<typeof AppfollowReviewSignalExtraApi>

export const JudgemeReviewsReviewSignalExtraApi = zod.object({
    rating: zod.union([zod.string(), zod.null()]),
    product_title: zod.union([zod.string(), zod.null()]),
    verified: zod.union([zod.string(), zod.null()]),
    created_at: zod.union([zod.string(), zod.null()]),
})

export type JudgemeReviewsReviewSignalExtraApi = zod.input<typeof JudgemeReviewsReviewSignalExtraApi>
export type JudgemeReviewsReviewSignalExtraApiOutput = zod.output<typeof JudgemeReviewsReviewSignalExtraApi>

export const IntercomTicketSignalExtraApi = zod.object({
    state: zod.union([zod.string(), zod.null()]),
    priority: zod.union([zod.string(), zod.null()]),
    admin_assignee_id: zod.union([zod.string(), zod.null()]),
    created_at: zod.union([zod.string(), zod.null()]),
})

export type IntercomTicketSignalExtraApi = zod.input<typeof IntercomTicketSignalExtraApi>
export type IntercomTicketSignalExtraApiOutput = zod.output<typeof IntercomTicketSignalExtraApi>

export const HubspotTicketSignalExtraApi = zod.object({
    hs_ticket_priority: zod.union([zod.string(), zod.null()]),
    hs_pipeline_stage: zod.union([zod.string(), zod.null()]),
    hs_ticket_category: zod.union([zod.string(), zod.null()]),
    createdate: zod.union([zod.string(), zod.null()]),
})

export type HubspotTicketSignalExtraApi = zod.input<typeof HubspotTicketSignalExtraApi>
export type HubspotTicketSignalExtraApiOutput = zod.output<typeof HubspotTicketSignalExtraApi>

export const GoogleSearchConsoleSearchOpportunitySignalExtraApi = zod.object({
    page: zod.string(),
    query: zod.string(),
    date: zod.string(),
    clicks: zod.number(),
    impressions: zod.number(),
    ctr: zod.number(),
    position: zod.number(),
})

export type GoogleSearchConsoleSearchOpportunitySignalExtraApi = zod.input<
    typeof GoogleSearchConsoleSearchOpportunitySignalExtraApi
>
export type GoogleSearchConsoleSearchOpportunitySignalExtraApiOutput = zod.output<
    typeof GoogleSearchConsoleSearchOpportunitySignalExtraApi
>
