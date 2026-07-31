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

export const ReviewBlindSpotsConfigApi = zod.object({
    skill_name: zod
        .string()
        .describe("Name of the `review-hog-blind-spots-\*` skill this row represents (the sweep's identity)."),
    active: zod
        .boolean()
        .describe("Whether this blind-spots skill runs the sweep on the requesting user's PR reviews on this project."),
    description: zod.string().describe("The blind-spots skill's description, for display in the config UI."),
    body: zod.string().describe("The blind-spots skill's SKILL.md body, for the read-only skill viewer."),
})

export type ReviewBlindSpotsConfigApi = zod.input<typeof ReviewBlindSpotsConfigApi>
export type ReviewBlindSpotsConfigApiOutput = zod.output<typeof ReviewBlindSpotsConfigApi>

export const PatchedReviewBlindSpotsConfigSelectApi = zod.object({
    active: zod
        .boolean()
        .optional()
        .describe(
            "Set true to make this the single blind-spots skill that runs on the user's PR reviews. Only true is accepted — the blind-spot check is single-active, so you switch by selecting a different skill, not by deactivating the current one."
        ),
})

export type PatchedReviewBlindSpotsConfigSelectApi = zod.input<typeof PatchedReviewBlindSpotsConfigSelectApi>
export type PatchedReviewBlindSpotsConfigSelectApiOutput = zod.output<typeof PatchedReviewBlindSpotsConfigSelectApi>

export const ReviewPerspectiveConfigApi = zod.object({
    skill_name: zod
        .string()
        .describe("Name of the `review-hog-perspective-\*` skill this row toggles (the perspective's identity)."),
    enabled: zod.boolean().describe("Whether this perspective runs on the acting user's PR reviews on this project."),
    description: zod.string().describe("The perspective skill's description, for display in the config UI."),
    body: zod.string().describe("The perspective skill's SKILL.md body, for the read-only skill viewer."),
})

export type ReviewPerspectiveConfigApi = zod.input<typeof ReviewPerspectiveConfigApi>
export type ReviewPerspectiveConfigApiOutput = zod.output<typeof ReviewPerspectiveConfigApi>

export const PatchedReviewPerspectiveConfigUpdateApi = zod.object({
    enabled: zod
        .boolean()
        .optional()
        .describe("Set true to run this perspective on the user's PR reviews, false to stop running it."),
})

export type PatchedReviewPerspectiveConfigUpdateApi = zod.input<typeof PatchedReviewPerspectiveConfigUpdateApi>
export type PatchedReviewPerspectiveConfigUpdateApiOutput = zod.output<typeof PatchedReviewPerspectiveConfigUpdateApi>

export const ReviewStageEnumApi = zod
    .enum(['fetching', 'chunking', 'selecting', 'reviewing', 'deduplicating', 'validating', 'finalizing'])
    .describe(
        '\* `fetching` - fetching\n\* `chunking` - chunking\n\* `selecting` - selecting\n\* `reviewing` - reviewing\n\* `deduplicating` - deduplicating\n\* `validating` - validating\n\* `finalizing` - finalizing'
    )

export type ReviewStageEnumApi = zod.input<typeof ReviewStageEnumApi>
export type ReviewStageEnumApiOutput = zod.output<typeof ReviewStageEnumApi>

export const ReviewProgressApi = zod.object({
    review_stage: ReviewStageEnumApi.describe(
        "How far the in-flight review turn has come: fetching the diff, chunking, picking each chunk's perspectives, reviewing chunks, merging overlapping findings, validating them, or finalizing (building and publishing the review).\n\n\* `fetching` - fetching\n\* `chunking` - chunking\n\* `selecting` - selecting\n\* `reviewing` - reviewing\n\* `deduplicating` - deduplicating\n\* `validating` - validating\n\* `finalizing` - finalizing"
    ),
    done: zod.number().nullable().describe('Work units finished within the stage; null when the stage has no counter.'),
    total: zod.number().nullable().describe('Work units the stage expects in total; null when unknown.'),
})

export type ReviewProgressApi = zod.input<typeof ReviewProgressApi>
export type ReviewProgressApiOutput = zod.output<typeof ReviewProgressApi>

export const ReviewRecentReviewApi = zod.object({
    id: zod.uuid().describe("The review report's id, for fetching the review's detail."),
    repository: zod.string().describe('The reviewed repository, as `owner\/repo`.'),
    pr_number: zod
        .number()
        .nullable()
        .describe("The reviewed pull request's number; null for a branch target with no PR yet."),
    pr_title: zod
        .string()
        .nullable()
        .describe("The pull request's title, from the latest reviewed snapshot; null if unknown."),
    pr_author: zod.string().nullable().describe("The pull request author's GitHub login; null if unknown."),
    additions: zod.number().nullable().describe('Lines added by the PR; null if unknown.'),
    deletions: zod.number().nullable().describe('Lines deleted by the PR; null if unknown.'),
    changed_files: zod.number().nullable().describe('Files the PR changes; null if unknown.'),
    head_branch: zod.string().describe("The pull request's head branch."),
    github_url: zod
        .string()
        .describe(
            'Where to see the review on GitHub: the pull request when its URL is known, otherwise the head branch.'
        ),
    run_count: zod.number().describe('How many review turns have completed on this report.'),
    last_run_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the latest review turn completed; null while the first is in flight.'),
    published: zod.boolean().describe('Whether a review has been published back to GitHub.'),
    in_progress: zod
        .boolean()
        .describe('Whether a review turn is running on this report right now (activity within the last 30 minutes).'),
    progress: zod
        .union([ReviewProgressApi, zod.null()])
        .describe("The in-flight turn's stage and counters; null unless `in_progress`."),
    must_fix_count: zod.number().describe("The latest turn's valid findings at must_fix effective priority."),
    should_fix_count: zod.number().describe("The latest turn's valid findings at should_fix effective priority."),
    consider_count: zod.number().describe("The latest turn's valid findings at consider effective priority."),
    candidate_count: zod.number().describe('All findings the latest turn raised after dedupe, before validation.'),
    dismissed_count: zod
        .number()
        .describe("The latest turn's findings the validator dismissed as not worth publishing."),
    files_reviewed: zod
        .number()
        .nullable()
        .describe(
            'Meaningful files the latest turn actually read, after skipping generated\/lock\/snapshot files; null if unknown.'
        ),
    chunk_count: zod
        .number()
        .nullable()
        .describe('Reviewable chunks the latest turn split the PR into; null if unknown.'),
    perspective_count: zod
        .number()
        .nullable()
        .describe('Review perspectives that read each chunk in the latest turn; null if unknown.'),
    perspective_issue_count: zod
        .number()
        .nullable()
        .describe('Raw issues the perspectives raised in the latest turn, before dedupe; null if unknown.'),
    blind_spot_issue_count: zod
        .number()
        .nullable()
        .describe('Raw issues the blind-spot sweep added in the latest turn, before dedupe; null if unknown.'),
})

export type ReviewRecentReviewApi = zod.input<typeof ReviewRecentReviewApi>
export type ReviewRecentReviewApiOutput = zod.output<typeof ReviewRecentReviewApi>

export const ReviewRecentReviewsPageApi = zod.object({
    results: zod
        .array(ReviewRecentReviewApi)
        .describe('The scoped reviews: in-progress runs first, then completed newest first.'),
    has_more: zod
        .boolean()
        .describe('Whether reviews exist beyond this page — drives the list\'s \"Show more\" button.'),
})

export type ReviewRecentReviewsPageApi = zod.input<typeof ReviewRecentReviewsPageApi>
export type ReviewRecentReviewsPageApiOutput = zod.output<typeof ReviewRecentReviewsPageApi>

export const ReviewSelectionChunkApi = zod.object({
    chunk_id: zod.number().describe('The chunk this row describes, as numbered by the chunker.'),
    chunk_type: zod
        .string()
        .nullable()
        .describe("The chunker's category for the chunk; null on the deterministic single-chunk path."),
    files: zod.array(zod.string()).describe("The chunk's files, from the turn's chunk set."),
    perspectives: zod.array(zod.string()).describe('Perspectives the selector ran on this chunk, in pass order.'),
    skipped: zod.array(zod.string()).describe('Roster perspectives the selector skipped on this chunk, in pass order.'),
    reason: zod.string().describe("The selector's one-line reasoning for this chunk's picks."),
})

export type ReviewSelectionChunkApi = zod.input<typeof ReviewSelectionChunkApi>
export type ReviewSelectionChunkApiOutput = zod.output<typeof ReviewSelectionChunkApi>

export const ReviewPerspectiveSelectionApi = zod.object({
    roster: zod.array(zod.string()).describe('Every enabled perspective the selector chose from, in pass order.'),
    chunks: zod.array(ReviewSelectionChunkApi).describe('Per-chunk picks with reasons, in chunk order.'),
})

export type ReviewPerspectiveSelectionApi = zod.input<typeof ReviewPerspectiveSelectionApi>
export type ReviewPerspectiveSelectionApiOutput = zod.output<typeof ReviewPerspectiveSelectionApi>

export const ReviewIssuePriorityEnumApi = zod
    .enum(['must_fix', 'should_fix', 'consider'])
    .describe('\* `must_fix` - must_fix\n\* `should_fix` - should_fix\n\* `consider` - consider')

export type ReviewIssuePriorityEnumApi = zod.input<typeof ReviewIssuePriorityEnumApi>
export type ReviewIssuePriorityEnumApiOutput = zod.output<typeof ReviewIssuePriorityEnumApi>

export const ReviewFindingLineRangeApi = zod.object({
    start: zod.number().describe('First affected line.'),
    end: zod.number().nullable().describe('Last affected line; null for a single line.'),
})

export type ReviewFindingLineRangeApi = zod.input<typeof ReviewFindingLineRangeApi>
export type ReviewFindingLineRangeApiOutput = zod.output<typeof ReviewFindingLineRangeApi>

export const ValidatorCategoryEnumApi = zod
    .enum([
        'bug',
        'security',
        'performance',
        'code_quality',
        'best_practice',
        'documentation',
        'testing',
        'accessibility',
        'compatibility',
    ])
    .describe(
        '\* `bug` - bug\n\* `security` - security\n\* `performance` - performance\n\* `code_quality` - code_quality\n\* `best_practice` - best_practice\n\* `documentation` - documentation\n\* `testing` - testing\n\* `accessibility` - accessibility\n\* `compatibility` - compatibility'
    )

export type ValidatorCategoryEnumApi = zod.input<typeof ValidatorCategoryEnumApi>
export type ValidatorCategoryEnumApiOutput = zod.output<typeof ValidatorCategoryEnumApi>

export const ReviewFindingApi = zod.object({
    title: zod.string().describe('One-line summary of the finding.'),
    file: zod.string().describe('Repository-relative path of the affected file.'),
    lines: zod.array(ReviewFindingLineRangeApi).describe('Affected line ranges within the file.'),
    body: zod.string().describe('Description of the problem.'),
    suggestion: zod.string().describe('The specific fix or improvement the reviewer proposes.'),
    effective_priority: ReviewIssuePriorityEnumApi.describe(
        "The priority that gates publishing: the validator's override when set, else the reviewer's.\n\n\* `must_fix` - must_fix\n\* `should_fix` - should_fix\n\* `consider` - consider"
    ),
    reviewer_priority: ReviewIssuePriorityEnumApi.describe(
        "The reviewer's original priority, before any validator override.\n\n\* `must_fix` - must_fix\n\* `should_fix` - should_fix\n\* `consider` - consider"
    ),
    source_perspective: zod
        .string()
        .nullable()
        .describe('The review skill that produced the finding (perspective or blind-spot sweep).'),
    validator_category: zod
        .union([ValidatorCategoryEnumApi, zod.null()])
        .describe(
            "The validator's category for the finding; null when it didn't set one.\n\n\* `bug` - bug\n\* `security` - security\n\* `performance` - performance\n\* `code_quality` - code_quality\n\* `best_practice` - best_practice\n\* `documentation` - documentation\n\* `testing` - testing\n\* `accessibility` - accessibility\n\* `compatibility` - compatibility"
        ),
    validator_note: zod.string().describe("The validator's argumentation for keeping or dismissing the finding."),
})

export type ReviewFindingApi = zod.input<typeof ReviewFindingApi>
export type ReviewFindingApiOutput = zod.output<typeof ReviewFindingApi>

export const ReviewDetailApi = zod.object({
    id: zod.uuid().describe("The review report's id, for fetching the review's detail."),
    repository: zod.string().describe('The reviewed repository, as `owner\/repo`.'),
    pr_number: zod
        .number()
        .nullable()
        .describe("The reviewed pull request's number; null for a branch target with no PR yet."),
    pr_title: zod
        .string()
        .nullable()
        .describe("The pull request's title, from the latest reviewed snapshot; null if unknown."),
    pr_author: zod.string().nullable().describe("The pull request author's GitHub login; null if unknown."),
    additions: zod.number().nullable().describe('Lines added by the PR; null if unknown.'),
    deletions: zod.number().nullable().describe('Lines deleted by the PR; null if unknown.'),
    changed_files: zod.number().nullable().describe('Files the PR changes; null if unknown.'),
    head_branch: zod.string().describe("The pull request's head branch."),
    github_url: zod
        .string()
        .describe(
            'Where to see the review on GitHub: the pull request when its URL is known, otherwise the head branch.'
        ),
    run_count: zod.number().describe('How many review turns have completed on this report.'),
    last_run_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the latest review turn completed; null while the first is in flight.'),
    published: zod.boolean().describe('Whether a review has been published back to GitHub.'),
    in_progress: zod
        .boolean()
        .describe('Whether a review turn is running on this report right now (activity within the last 30 minutes).'),
    progress: zod
        .union([ReviewProgressApi, zod.null()])
        .describe("The in-flight turn's stage and counters; null unless `in_progress`."),
    must_fix_count: zod.number().describe("The latest turn's valid findings at must_fix effective priority."),
    should_fix_count: zod.number().describe("The latest turn's valid findings at should_fix effective priority."),
    consider_count: zod.number().describe("The latest turn's valid findings at consider effective priority."),
    candidate_count: zod.number().describe('All findings the latest turn raised after dedupe, before validation.'),
    dismissed_count: zod
        .number()
        .describe("The latest turn's findings the validator dismissed as not worth publishing."),
    files_reviewed: zod
        .number()
        .nullable()
        .describe(
            'Meaningful files the latest turn actually read, after skipping generated\/lock\/snapshot files; null if unknown.'
        ),
    chunk_count: zod
        .number()
        .nullable()
        .describe('Reviewable chunks the latest turn split the PR into; null if unknown.'),
    perspective_count: zod
        .number()
        .nullable()
        .describe('Review perspectives that read each chunk in the latest turn; null if unknown.'),
    perspective_issue_count: zod
        .number()
        .nullable()
        .describe('Raw issues the perspectives raised in the latest turn, before dedupe; null if unknown.'),
    blind_spot_issue_count: zod
        .number()
        .nullable()
        .describe('Raw issues the blind-spot sweep added in the latest turn, before dedupe; null if unknown.'),
    head_sha: zod
        .string()
        .nullable()
        .describe('The PR head commit the latest turn reviewed — anchors GitHub links to the exact code.'),
    perspective_selection: zod
        .union([ReviewPerspectiveSelectionApi, zod.null()])
        .describe(
            "The selector's per-chunk perspective plan for the latest turn; null when the turn ran without a selection (selector unavailable, failed, or the run predates it)."
        ),
    report_markdown: zod.string().describe('The rendered review body published to GitHub, as markdown.'),
    run_urgency_threshold: zod
        .union([ReviewIssuePriorityEnumApi, zod.null()])
        .describe(
            "The urgency threshold the completed turn's publishing gated on (stamped at finalize from the run's own resolve snapshot); null for turns that predate its recording — readers fall back to the viewer's current setting as an approximation.\n\n\* `must_fix` - must_fix\n\* `should_fix` - should_fix\n\* `consider` - consider"
        ),
    findings: zod.array(ReviewFindingApi).describe("The latest turn's validated findings, most urgent first."),
    dismissed_findings: zod
        .array(ReviewFindingApi)
        .describe("The latest turn's findings the validator dismissed, with its reasoning."),
})

export type ReviewDetailApi = zod.input<typeof ReviewDetailApi>
export type ReviewDetailApiOutput = zod.output<typeof ReviewDetailApi>

export const ReviewPerspectiveStatItemApi = zod.object({
    skill_name: zod.string().describe('The review skill (perspective or blind-spot sweep) that raised the findings.'),
    raised: zod.number().describe('Findings this skill raised across the aggregated reviews (post-dedupe candidates).'),
    kept: zod.number().describe('Of those, findings the validator kept.'),
    dismissed: zod.number().describe('Of those, findings the validator dismissed.'),
})

export type ReviewPerspectiveStatItemApi = zod.input<typeof ReviewPerspectiveStatItemApi>
export type ReviewPerspectiveStatItemApiOutput = zod.output<typeof ReviewPerspectiveStatItemApi>

export const ReviewPerspectiveStatsApi = zod.object({
    report_count: zod.number().describe('How many recent completed reviews the stats aggregate over.'),
    perspectives: zod
        .array(ReviewPerspectiveStatItemApi)
        .describe('Per-skill effectiveness across those reviews, most kept findings first.'),
})

export type ReviewPerspectiveStatsApi = zod.input<typeof ReviewPerspectiveStatsApi>
export type ReviewPerspectiveStatsApiOutput = zod.output<typeof ReviewPerspectiveStatsApi>

export const ReviewTriggerRequestApi = zod.object({
    pr_url: zod
        .string()
        .describe(
            "GitHub pull request URL to review, e.g. 'https:\/\/github.com\/PostHog\/posthog.com\/pull\/123'. The repository must be accessible to the project's GitHub App installation."
        ),
})

export type ReviewTriggerRequestApi = zod.input<typeof ReviewTriggerRequestApi>
export type ReviewTriggerRequestApiOutput = zod.output<typeof ReviewTriggerRequestApi>

export const ReviewTriggerResponseApi = zod.object({
    workflow_id: zod
        .string()
        .describe('Temporal workflow id for the started review run; empty when no run was started.'),
    status: zod
        .string()
        .describe(
            "Run lifecycle marker: 'started' when the review was queued, 'already_reviewed' when the pull request's current commit already has a published review (no new run starts)."
        ),
})

export type ReviewTriggerResponseApi = zod.input<typeof ReviewTriggerResponseApi>
export type ReviewTriggerResponseApiOutput = zod.output<typeof ReviewTriggerResponseApi>

export const ReviewTriggerErrorApi = zod.object({
    error: zod.string().describe('Human-readable explanation of why the trigger was rejected.'),
})

export type ReviewTriggerErrorApi = zod.input<typeof ReviewTriggerErrorApi>
export type ReviewTriggerErrorApiOutput = zod.output<typeof ReviewTriggerErrorApi>

export const UrgencyThresholdEnumApi = zod
    .enum(['consider', 'should_fix', 'must_fix'])
    .describe('\* `consider` - Consider\n\* `should_fix` - Should Fix\n\* `must_fix` - Must Fix')

export type UrgencyThresholdEnumApi = zod.input<typeof UrgencyThresholdEnumApi>
export type UrgencyThresholdEnumApiOutput = zod.output<typeof UrgencyThresholdEnumApi>

export const ReviewUserSettingsApi = zod.object({
    review_inbox_prs: zod
        .boolean()
        .optional()
        .describe(
            "Automatically review pull requests opened by self-driving implementations from the user's Inbox: ReviewHog reviews each one and posts its findings to the pull request."
        ),
    stamphog_review_inbox_prs: zod
        .boolean()
        .optional()
        .describe(
            "Also have hosted Stamphog review those same Inbox pull requests: an approve-first review that posts a real GitHub approval when the change passes, and a comment when it doesn't. Only takes effect when the project has a synced, enabled Stamphog repository (see stamphog_connected)."
        ),
    review_labeled_prs: zod
        .boolean()
        .optional()
        .describe(
            "Review the user's pull requests when the trigger label is added on GitHub. On by default; turning it off makes the label trigger skip PRs this user authored."
        ),
    urgency_threshold: UrgencyThresholdEnumApi.optional().describe(
        "Minimum priority a validated finding needs to be published: 'consider' (default) publishes everything, 'should_fix' drops consider-level findings, 'must_fix' publishes only blocking issues.\n\n\* `consider` - Consider\n\* `should_fix` - Should Fix\n\* `must_fix` - Must Fix"
    ),
    can_trigger_reviews: zod
        .boolean()
        .describe(
            "Whether reviews can be started from this project's Code review page (the UI trigger is limited to the designated ReviewHog team while the product is in alpha)."
        ),
    stamphog_connected: zod
        .boolean()
        .describe(
            'Whether this project has at least one synced, enabled Stamphog repository. When false, the stamphog_review_inbox_prs toggle has nothing to act on and the UI renders it disabled with a pointer to connect the Stamphog GitHub App.'
        ),
})

export type ReviewUserSettingsApi = zod.input<typeof ReviewUserSettingsApi>
export type ReviewUserSettingsApiOutput = zod.output<typeof ReviewUserSettingsApi>

export const PatchedReviewUserSettingsApi = zod.object({
    review_inbox_prs: zod
        .boolean()
        .optional()
        .describe(
            "Automatically review pull requests opened by self-driving implementations from the user's Inbox: ReviewHog reviews each one and posts its findings to the pull request."
        ),
    stamphog_review_inbox_prs: zod
        .boolean()
        .optional()
        .describe(
            "Also have hosted Stamphog review those same Inbox pull requests: an approve-first review that posts a real GitHub approval when the change passes, and a comment when it doesn't. Only takes effect when the project has a synced, enabled Stamphog repository (see stamphog_connected)."
        ),
    review_labeled_prs: zod
        .boolean()
        .optional()
        .describe(
            "Review the user's pull requests when the trigger label is added on GitHub. On by default; turning it off makes the label trigger skip PRs this user authored."
        ),
    urgency_threshold: UrgencyThresholdEnumApi.optional().describe(
        "Minimum priority a validated finding needs to be published: 'consider' (default) publishes everything, 'should_fix' drops consider-level findings, 'must_fix' publishes only blocking issues.\n\n\* `consider` - Consider\n\* `should_fix` - Should Fix\n\* `must_fix` - Must Fix"
    ),
    can_trigger_reviews: zod
        .boolean()
        .optional()
        .describe(
            "Whether reviews can be started from this project's Code review page (the UI trigger is limited to the designated ReviewHog team while the product is in alpha)."
        ),
    stamphog_connected: zod
        .boolean()
        .optional()
        .describe(
            'Whether this project has at least one synced, enabled Stamphog repository. When false, the stamphog_review_inbox_prs toggle has nothing to act on and the UI renders it disabled with a pointer to connect the Stamphog GitHub App.'
        ),
})

export type PatchedReviewUserSettingsApi = zod.input<typeof PatchedReviewUserSettingsApi>
export type PatchedReviewUserSettingsApiOutput = zod.output<typeof PatchedReviewUserSettingsApi>

export const ReviewValidatorConfigApi = zod.object({
    skill_name: zod
        .string()
        .describe("Name of the `review-hog-validation-\*` skill this row represents (the validator's identity)."),
    active: zod
        .boolean()
        .describe("Whether this validator is the one that validates the requesting user's PR reviews on this project."),
    description: zod.string().describe("The validator skill's description, for display in the config UI."),
    body: zod.string().describe("The validator skill's SKILL.md body, for the read-only skill viewer."),
})

export type ReviewValidatorConfigApi = zod.input<typeof ReviewValidatorConfigApi>
export type ReviewValidatorConfigApiOutput = zod.output<typeof ReviewValidatorConfigApi>

export const PatchedReviewValidatorConfigSelectApi = zod.object({
    active: zod
        .boolean()
        .optional()
        .describe(
            "Set true to make this the single validator that runs on the user's PR reviews. Only true is accepted — validators are single-active, so you switch by selecting a different one, not by deactivating the current one."
        ),
})

export type PatchedReviewValidatorConfigSelectApi = zod.input<typeof PatchedReviewValidatorConfigSelectApi>
export type PatchedReviewValidatorConfigSelectApiOutput = zod.output<typeof PatchedReviewValidatorConfigSelectApi>
