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
 * Asks the decision model which of several code excerpts shows what a finding describes. Returns null when it is unsure. 404 when the person may not use Jev.
 * @summary Pick the code excerpt a finding describes
 */
export const todayExcerptChoiceCreateBodyFindingMax = 6000

export const todayExcerptChoiceCreateBodyExcerptsItemMax = 2000

export const todayExcerptChoiceCreateBodyExcerptsMin = 2
export const todayExcerptChoiceCreateBodyExcerptsMax = 5

export const TodayExcerptChoiceCreateBody = /* @__PURE__ */ zod.object({
    finding: zod
        .string()
        .max(todayExcerptChoiceCreateBodyFindingMax)
        .describe('The finding the code excerpts should show.'),
    excerpts: zod
        .array(zod.string().max(todayExcerptChoiceCreateBodyExcerptsItemMax))
        .min(todayExcerptChoiceCreateBodyExcerptsMin)
        .max(todayExcerptChoiceCreateBodyExcerptsMax)
        .describe('Candidate code excerpts, best scored first.'),
})
