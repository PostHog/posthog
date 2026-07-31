/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import {
    PatchedReviewBlindSpotsConfigSelectApi,
    PatchedReviewPerspectiveConfigUpdateApi,
    PatchedReviewUserSettingsApi,
    PatchedReviewValidatorConfigSelectApi,
    ReviewTriggerRequestApi,
} from './api.zod.schemas'

/**
 * Make a `review-hog-blind-spots-*` skill the single sweep that runs on the requesting user's PR reviews, switching the user's other blind-spots skills off in the same call. Only skills visible to the user — the canonical plus the customs they authored — can be selected; anything else 404s. Upserts the per-user config row, so selecting a freshly authored custom skill works in one call.
 * @summary Select the active blind-spots skill
 */
export const ReviewHogBlindSpotsPartialUpdateBody = PatchedReviewBlindSpotsConfigSelectApi

/**
 * Toggle whether a `review-hog-perspective-*` skill runs on the requesting user's PR reviews. Only skills visible to the user — the canonicals plus the customs they authored — can be toggled; anything else 404s. Upserts the per-user config row, so enabling a freshly authored custom perspective works in one call. Rejected if it would leave the user with no enabled perspective.
 * @summary Enable or disable a review perspective
 */
export const ReviewHogPerspectivesPartialUpdateBody = PatchedReviewPerspectiveConfigUpdateApi

/**
 * Start a ReviewHog review of any pull request the project's GitHub App installation can access, and publish it back to the PR. The requesting user is the review's acting user: their enabled perspectives, blind-spot check, validator, and urgency threshold drive the run, and it appears under their recent reviews. Nonexistent, closed, and fork PRs are rejected synchronously; a PR whose current commit already has a published review returns 'already_reviewed' without starting a run, and triggering a PR whose review is currently running joins the in-flight run. Otherwise non-blocking: returns the Temporal workflow id immediately while the review runs in the worker.
 * @summary Start a review of a pull request
 */
export const ReviewHogReviewsTriggerCreateBody = ReviewTriggerRequestApi

/**
 * Partially update the requesting user's ReviewHog settings for this project. Only the provided fields change.
 * @summary Update the user's ReviewHog settings
 */
export const ReviewHogSettingsPartialUpdateBody = PatchedReviewUserSettingsApi

/**
 * Make a `review-hog-validation-*` skill the single validator that runs on the requesting user's PR reviews, switching the user's other validators off in the same call. Only skills visible to the user — the canonical plus the customs they authored — can be selected; anything else 404s. Upserts the per-user config row, so selecting a freshly authored custom validator works in one call.
 * @summary Select the active review validator
 */
export const ReviewHogValidatorsPartialUpdateBody = PatchedReviewValidatorConfigSelectApi
