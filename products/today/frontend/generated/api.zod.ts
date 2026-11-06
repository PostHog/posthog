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

/**
 * Replaces the numbers the person keeps at the start of the key numbers, in order. Repeated keys are dropped and only the first 4 are kept. The next highlights request computes the new numbers. 404 when the person does not have the new navigation.
 * @summary Set the numbers the person keeps
 */
export const todayPulsePinsUpdateBodyPinsItemKeyMax = 200

export const todayPulsePinsUpdateBodyPinsItemNameMax = 400

export const TodayPulsePinsUpdateBody = /* @__PURE__ */ zod.object({
    pins: zod
        .array(
            zod.object({
                key: zod
                    .string()
                    .max(todayPulsePinsUpdateBodyPinsItemKeyMax)
                    .describe(
                        'Key of the number to keep: a key metric setting such as signup_event, or insight:<short_id>.'
                    ),
                name: zod
                    .string()
                    .max(todayPulsePinsUpdateBodyPinsItemNameMax)
                    .describe('Name to show for the number until the highlights compute its value.'),
                dashboard_id: zod
                    .number()
                    .nullish()
                    .describe(
                        'For an insight pinned from a dashboard tile, the dashboard whose filters it keeps. Null otherwise.'
                    ),
            })
        )
        .describe(
            'Numbers the person keeps at the start of the key numbers, in order. Suggestions fill the free places. Only the first 4 distinct keys are kept. At most 20 entries.'
        ),
})
