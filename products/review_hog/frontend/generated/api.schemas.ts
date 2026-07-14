/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface ReviewBlindSpotsConfigApi {
    /** Name of the `review-hog-blind-spots-*` skill this row represents (the sweep's identity). */
    skill_name: string
    /** Whether this blind-spots skill runs the sweep on the requesting user's PR reviews on this project. */
    active: boolean
    /** The blind-spots skill's description, for display in the config UI. */
    description: string
    /** The blind-spots skill's SKILL.md body, for the read-only skill viewer. */
    body: string
}

export interface PatchedReviewBlindSpotsConfigSelectApi {
    /** Set true to make this the single blind-spots skill that runs on the user's PR reviews. Only true is accepted — the blind-spot check is single-active, so you switch by selecting a different skill, not by deactivating the current one. */
    active?: boolean
}

export interface ReviewPerspectiveConfigApi {
    /** Name of the `review-hog-perspective-*` skill this row toggles (the perspective's identity). */
    skill_name: string
    /** Whether this perspective runs on the acting user's PR reviews on this project. */
    enabled: boolean
    /** The perspective skill's description, for display in the config UI. */
    description: string
    /** The perspective skill's SKILL.md body, for the read-only skill viewer. */
    body: string
}

export interface PatchedReviewPerspectiveConfigUpdateApi {
    /** Set true to run this perspective on the user's PR reviews, false to stop running it. */
    enabled?: boolean
}

/**
 * * `fetching` - fetching
 * * `chunking` - chunking
 * * `selecting` - selecting
 * * `reviewing` - reviewing
 * * `deduplicating` - deduplicating
 * * `validating` - validating
 * * `finalizing` - finalizing
 */
export type ReviewStageEnumApi = (typeof ReviewStageEnumApi)[keyof typeof ReviewStageEnumApi]

export const ReviewStageEnumApi = {
    Fetching: 'fetching',
    Chunking: 'chunking',
    Selecting: 'selecting',
    Reviewing: 'reviewing',
    Deduplicating: 'deduplicating',
    Validating: 'validating',
    Finalizing: 'finalizing',
} as const

export interface ReviewProgressApi {
    /** How far the in-flight review turn has come: fetching the diff, chunking, picking each chunk's perspectives, reviewing chunks, merging overlapping findings, validating them, or finalizing (building and publishing the review).
     *
     * * `fetching` - fetching
     * * `chunking` - chunking
     * * `selecting` - selecting
     * * `reviewing` - reviewing
     * * `deduplicating` - deduplicating
     * * `validating` - validating
     * * `finalizing` - finalizing */
    review_stage: ReviewStageEnumApi
    /**
     * Work units finished within the stage; null when the stage has no counter.
     * @nullable
     */
    done: number | null
    /**
     * Work units the stage expects in total; null when unknown.
     * @nullable
     */
    total: number | null
}

export interface ReviewRecentReviewApi {
    /** The review report's id, for fetching the review's detail. */
    id: string
    /** The reviewed repository, as `owner/repo`. */
    repository: string
    /**
     * The reviewed pull request's number; null for a branch target with no PR yet.
     * @nullable
     */
    pr_number: number | null
    /**
     * The pull request's title, from the latest reviewed snapshot; null if unknown.
     * @nullable
     */
    pr_title: string | null
    /**
     * The pull request author's GitHub login; null if unknown.
     * @nullable
     */
    pr_author: string | null
    /**
     * Lines added by the PR; null if unknown.
     * @nullable
     */
    additions: number | null
    /**
     * Lines deleted by the PR; null if unknown.
     * @nullable
     */
    deletions: number | null
    /**
     * Files the PR changes; null if unknown.
     * @nullable
     */
    changed_files: number | null
    /** The pull request's head branch. */
    head_branch: string
    /** Where to see the review on GitHub: the pull request when its URL is known, otherwise the head branch. */
    github_url: string
    /** How many review turns have completed on this report. */
    run_count: number
    /**
     * When the latest review turn completed; null while the first is in flight.
     * @nullable
     */
    last_run_at: string | null
    /** Whether a review has been published back to GitHub. */
    published: boolean
    /** Whether a review turn is running on this report right now (activity within the last 30 minutes). */
    in_progress: boolean
    /** The in-flight turn's stage and counters; null unless `in_progress`. */
    progress: ReviewProgressApi | null
    /** The latest turn's valid findings at must_fix effective priority. */
    must_fix_count: number
    /** The latest turn's valid findings at should_fix effective priority. */
    should_fix_count: number
    /** The latest turn's valid findings at consider effective priority. */
    consider_count: number
    /** All findings the latest turn raised after dedupe, before validation. */
    candidate_count: number
    /** The latest turn's findings the validator dismissed as not worth publishing. */
    dismissed_count: number
    /**
     * Meaningful files the latest turn actually read, after skipping generated/lock/snapshot files; null if unknown.
     * @nullable
     */
    files_reviewed: number | null
    /**
     * Reviewable chunks the latest turn split the PR into; null if unknown.
     * @nullable
     */
    chunk_count: number | null
    /**
     * Review perspectives that read each chunk in the latest turn; null if unknown.
     * @nullable
     */
    perspective_count: number | null
    /**
     * Raw issues the perspectives raised in the latest turn, before dedupe; null if unknown.
     * @nullable
     */
    perspective_issue_count: number | null
    /**
     * Raw issues the blind-spot sweep added in the latest turn, before dedupe; null if unknown.
     * @nullable
     */
    blind_spot_issue_count: number | null
}

export interface ReviewSelectionChunkApi {
    /** The chunk this row describes, as numbered by the chunker. */
    chunk_id: number
    /**
     * The chunker's category for the chunk; null on the deterministic single-chunk path.
     * @nullable
     */
    chunk_type: string | null
    /** The chunk's files, from the turn's chunk set. */
    files: string[]
    /** Perspectives the selector ran on this chunk, in pass order. */
    perspectives: string[]
    /** Roster perspectives the selector skipped on this chunk, in pass order. */
    skipped: string[]
    /** The selector's one-line reasoning for this chunk's picks. */
    reason: string
}

export interface ReviewPerspectiveSelectionApi {
    /** Every enabled perspective the selector chose from, in pass order. */
    roster: string[]
    /** Per-chunk picks with reasons, in chunk order. */
    chunks: ReviewSelectionChunkApi[]
}

export interface ReviewFindingLineRangeApi {
    /** First affected line. */
    start: number
    /**
     * Last affected line; null for a single line.
     * @nullable
     */
    end: number | null
}

/**
 * * `must_fix` - must_fix
 * * `should_fix` - should_fix
 * * `consider` - consider
 */
export type ReviewIssuePriorityEnumApi = (typeof ReviewIssuePriorityEnumApi)[keyof typeof ReviewIssuePriorityEnumApi]

export const ReviewIssuePriorityEnumApi = {
    MustFix: 'must_fix',
    ShouldFix: 'should_fix',
    Consider: 'consider',
} as const

/**
 * * `bug` - bug
 * * `security` - security
 * * `performance` - performance
 * * `code_quality` - code_quality
 * * `best_practice` - best_practice
 * * `documentation` - documentation
 * * `testing` - testing
 * * `accessibility` - accessibility
 * * `compatibility` - compatibility
 */
export type ValidatorCategoryEnumApi = (typeof ValidatorCategoryEnumApi)[keyof typeof ValidatorCategoryEnumApi]

export const ValidatorCategoryEnumApi = {
    Bug: 'bug',
    Security: 'security',
    Performance: 'performance',
    CodeQuality: 'code_quality',
    BestPractice: 'best_practice',
    Documentation: 'documentation',
    Testing: 'testing',
    Accessibility: 'accessibility',
    Compatibility: 'compatibility',
} as const

export interface ReviewFindingApi {
    /** One-line summary of the finding. */
    title: string
    /** Repository-relative path of the affected file. */
    file: string
    /** Affected line ranges within the file. */
    lines: ReviewFindingLineRangeApi[]
    /** Description of the problem. */
    body: string
    /** The specific fix or improvement the reviewer proposes. */
    suggestion: string
    /** The priority that gates publishing: the validator's override when set, else the reviewer's.
     *
     * * `must_fix` - must_fix
     * * `should_fix` - should_fix
     * * `consider` - consider */
    effective_priority: ReviewIssuePriorityEnumApi
    /** The reviewer's original priority, before any validator override.
     *
     * * `must_fix` - must_fix
     * * `should_fix` - should_fix
     * * `consider` - consider */
    reviewer_priority: ReviewIssuePriorityEnumApi
    /**
     * The review skill that produced the finding (perspective or blind-spot sweep).
     * @nullable
     */
    source_perspective: string | null
    /** The validator's category for the finding; null when it didn't set one.
     *
     * * `bug` - bug
     * * `security` - security
     * * `performance` - performance
     * * `code_quality` - code_quality
     * * `best_practice` - best_practice
     * * `documentation` - documentation
     * * `testing` - testing
     * * `accessibility` - accessibility
     * * `compatibility` - compatibility */
    validator_category: ValidatorCategoryEnumApi | null
    /** The validator's argumentation for keeping or dismissing the finding. */
    validator_note: string
}

export interface ReviewDetailApi {
    /** The review report's id, for fetching the review's detail. */
    id: string
    /** The reviewed repository, as `owner/repo`. */
    repository: string
    /**
     * The reviewed pull request's number; null for a branch target with no PR yet.
     * @nullable
     */
    pr_number: number | null
    /**
     * The pull request's title, from the latest reviewed snapshot; null if unknown.
     * @nullable
     */
    pr_title: string | null
    /**
     * The pull request author's GitHub login; null if unknown.
     * @nullable
     */
    pr_author: string | null
    /**
     * Lines added by the PR; null if unknown.
     * @nullable
     */
    additions: number | null
    /**
     * Lines deleted by the PR; null if unknown.
     * @nullable
     */
    deletions: number | null
    /**
     * Files the PR changes; null if unknown.
     * @nullable
     */
    changed_files: number | null
    /** The pull request's head branch. */
    head_branch: string
    /** Where to see the review on GitHub: the pull request when its URL is known, otherwise the head branch. */
    github_url: string
    /** How many review turns have completed on this report. */
    run_count: number
    /**
     * When the latest review turn completed; null while the first is in flight.
     * @nullable
     */
    last_run_at: string | null
    /** Whether a review has been published back to GitHub. */
    published: boolean
    /** Whether a review turn is running on this report right now (activity within the last 30 minutes). */
    in_progress: boolean
    /** The in-flight turn's stage and counters; null unless `in_progress`. */
    progress: ReviewProgressApi | null
    /** The latest turn's valid findings at must_fix effective priority. */
    must_fix_count: number
    /** The latest turn's valid findings at should_fix effective priority. */
    should_fix_count: number
    /** The latest turn's valid findings at consider effective priority. */
    consider_count: number
    /** All findings the latest turn raised after dedupe, before validation. */
    candidate_count: number
    /** The latest turn's findings the validator dismissed as not worth publishing. */
    dismissed_count: number
    /**
     * Meaningful files the latest turn actually read, after skipping generated/lock/snapshot files; null if unknown.
     * @nullable
     */
    files_reviewed: number | null
    /**
     * Reviewable chunks the latest turn split the PR into; null if unknown.
     * @nullable
     */
    chunk_count: number | null
    /**
     * Review perspectives that read each chunk in the latest turn; null if unknown.
     * @nullable
     */
    perspective_count: number | null
    /**
     * Raw issues the perspectives raised in the latest turn, before dedupe; null if unknown.
     * @nullable
     */
    perspective_issue_count: number | null
    /**
     * Raw issues the blind-spot sweep added in the latest turn, before dedupe; null if unknown.
     * @nullable
     */
    blind_spot_issue_count: number | null
    /**
     * The PR head commit the latest turn reviewed — anchors GitHub links to the exact code.
     * @nullable
     */
    head_sha: string | null
    /** The selector's per-chunk perspective plan for the latest turn; null when the turn ran without a selection (selector unavailable, failed, or the run predates it). */
    perspective_selection: ReviewPerspectiveSelectionApi | null
    /** The rendered review body published to GitHub, as markdown. */
    report_markdown: string
    /** The latest turn's validated findings, most urgent first. */
    findings: ReviewFindingApi[]
    /** The latest turn's findings the validator dismissed, with its reasoning. */
    dismissed_findings: ReviewFindingApi[]
}

export interface ReviewPerspectiveStatItemApi {
    /** The review skill (perspective or blind-spot sweep) that raised the findings. */
    skill_name: string
    /** Findings this skill raised across the aggregated reviews (post-dedupe candidates). */
    raised: number
    /** Of those, findings the validator kept. */
    kept: number
    /** Of those, findings the validator dismissed. */
    dismissed: number
}

export interface ReviewPerspectiveStatsApi {
    /** How many recent completed reviews the stats aggregate over. */
    report_count: number
    /** Per-skill effectiveness across those reviews, most kept findings first. */
    perspectives: ReviewPerspectiveStatItemApi[]
}

/**
 * * `consider` - Consider
 * * `should_fix` - Should Fix
 * * `must_fix` - Must Fix
 */
export type UrgencyThresholdEnumApi = (typeof UrgencyThresholdEnumApi)[keyof typeof UrgencyThresholdEnumApi]

export const UrgencyThresholdEnumApi = {
    Consider: 'consider',
    ShouldFix: 'should_fix',
    MustFix: 'must_fix',
} as const

export interface ReviewUserSettingsApi {
    /** Automatically review pull requests opened by PostHog agents from the user's Inbox. Stored but not consumed yet — the Inbox auto-review trigger is not built. */
    review_inbox_prs?: boolean
    /** Review the user's pull requests when the trigger label is added on GitHub. On by default; turning it off makes the label trigger skip PRs this user authored. */
    review_labeled_prs?: boolean
    /** Minimum priority a validated finding needs to be published: 'consider' publishes everything, 'should_fix' (default) drops consider-level findings, 'must_fix' publishes only blocking issues.
     *
     * * `consider` - Consider
     * * `should_fix` - Should Fix
     * * `must_fix` - Must Fix */
    urgency_threshold?: UrgencyThresholdEnumApi
}

export interface PatchedReviewUserSettingsApi {
    /** Automatically review pull requests opened by PostHog agents from the user's Inbox. Stored but not consumed yet — the Inbox auto-review trigger is not built. */
    review_inbox_prs?: boolean
    /** Review the user's pull requests when the trigger label is added on GitHub. On by default; turning it off makes the label trigger skip PRs this user authored. */
    review_labeled_prs?: boolean
    /** Minimum priority a validated finding needs to be published: 'consider' publishes everything, 'should_fix' (default) drops consider-level findings, 'must_fix' publishes only blocking issues.
     *
     * * `consider` - Consider
     * * `should_fix` - Should Fix
     * * `must_fix` - Must Fix */
    urgency_threshold?: UrgencyThresholdEnumApi
}

export interface ReviewValidatorConfigApi {
    /** Name of the `review-hog-validation-*` skill this row represents (the validator's identity). */
    skill_name: string
    /** Whether this validator is the one that validates the requesting user's PR reviews on this project. */
    active: boolean
    /** The validator skill's description, for display in the config UI. */
    description: string
    /** The validator skill's SKILL.md body, for the read-only skill viewer. */
    body: string
}

export interface PatchedReviewValidatorConfigSelectApi {
    /** Set true to make this the single validator that runs on the user's PR reviews. Only true is accepted — validators are single-active, so you switch by selecting a different one, not by deactivating the current one. */
    active?: boolean
}
