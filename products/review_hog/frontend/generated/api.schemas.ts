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

export interface ReviewRecentReviewApi {
    /** The reviewed repository, as `owner/repo`. */
    repository: string
    /** The reviewed pull request's number. */
    pr_number: number
    /** The pull request's head branch. */
    head_branch: string
    /** Where to see the review on GitHub: the pull request when its URL is known, otherwise the head branch. */
    github_url: string
    /** How many review turns have completed on this report. */
    run_count: number
    /** When the latest review turn completed. */
    last_run_at: string
    /** Whether a review has been published back to GitHub. */
    published: boolean
    /** The latest turn's valid findings at must_fix effective priority. */
    must_fix_count: number
    /** The latest turn's valid findings at should_fix effective priority. */
    should_fix_count: number
    /** The latest turn's valid findings at consider effective priority. */
    consider_count: number
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
