/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Make a `review-hog-blind-spots-*` skill the single sweep that runs on the requesting user's PR reviews, switching the user's other blind-spots skills off in the same call. Upserts the per-user config row, so selecting a freshly authored custom skill works in one call.
 * @summary Select the active blind-spots skill
 */
export const ReviewHogBlindSpotsPartialUpdateBody = /* @__PURE__ */ zod.object({
    active: zod
        .boolean()
        .optional()
        .describe(
            "Set true to make this the single blind-spots skill that runs on the user's PR reviews. Only true is accepted — the blind-spot check is single-active, so you switch by selecting a different skill, not by deactivating the current one."
        ),
})

/**
 * Toggle whether a `review-hog-perspective-*` skill runs on the requesting user's PR reviews. Upserts the per-user config row, so enabling a freshly authored custom perspective works in one call. Rejected if it would leave the user with no enabled perspective.
 * @summary Enable or disable a review perspective
 */
export const ReviewHogPerspectivesPartialUpdateBody = /* @__PURE__ */ zod.object({
    enabled: zod
        .boolean()
        .optional()
        .describe("Set true to run this perspective on the user's PR reviews, false to stop running it."),
})

/**
 * Partially update the requesting user's ReviewHog settings for this project. Only the provided fields change.
 * @summary Update the user's ReviewHog settings
 */
export const ReviewHogSettingsPartialUpdateBody = /* @__PURE__ */ zod.object({
    review_inbox_prs: zod
        .boolean()
        .optional()
        .describe(
            "Automatically review pull requests opened by PostHog agents from the user's Inbox. Stored but not consumed yet — the Inbox auto-review trigger is not built."
        ),
    review_labeled_prs: zod
        .boolean()
        .optional()
        .describe(
            "Review the user's pull requests when the trigger label is added on GitHub. On by default; turning it off makes the label trigger skip PRs this user authored."
        ),
    urgency_threshold: zod
        .enum(['consider', 'should_fix', 'must_fix'])
        .describe('\* `consider` - Consider\n\* `should_fix` - Should Fix\n\* `must_fix` - Must Fix')
        .optional()
        .describe(
            "Minimum priority a validated finding needs to be published: 'consider' publishes everything, 'should_fix' (default) drops consider-level findings, 'must_fix' publishes only blocking issues.\n\n\* `consider` - Consider\n\* `should_fix` - Should Fix\n\* `must_fix` - Must Fix"
        ),
})

/**
 * Make a `review-hog-validation-*` skill the single validator that runs on the requesting user's PR reviews, switching the user's other validators off in the same call. Upserts the per-user config row, so selecting a freshly authored custom validator works in one call.
 * @summary Select the active review validator
 */
export const ReviewHogValidatorsPartialUpdateBody = /* @__PURE__ */ zod.object({
    active: zod
        .boolean()
        .optional()
        .describe(
            "Set true to make this the single validator that runs on the user's PR reviews. Only true is accepted — validators are single-active, so you switch by selecting a different one, not by deactivating the current one."
        ),
})
