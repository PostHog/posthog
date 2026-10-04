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
 * For each text the report page shows, the clauses that state the problem, its cause or the fix, each with sentences from the report that explain it. Only clauses the report explains further are returned, at most 2 across all texts. 404 when the report is missing or the person may not use Jev.
 * @summary Mark the key clauses of a report
 */
export const todayReportsKeyClausesCreateBodyRequestsItemTextMax = 4000

export const todayReportsKeyClausesCreateBodyRequestsItemRolesMax = 3

export const todayReportsKeyClausesCreateBodyRequestsMax = 3

export const TodayReportsKeyClausesCreateBody = /* @__PURE__ */ zod.object({
    requests: zod
        .array(
            zod.object({
                text: zod
                    .string()
                    .max(todayReportsKeyClausesCreateBodyRequestsItemTextMax)
                    .describe('A text the page shows, as the reader sees it.'),
                roles: zod
                    .array(
                        zod
                            .enum(['problem', 'cause', 'fix'])
                            .describe('\* `problem` - Problem\n\* `cause` - Cause\n\* `fix` - Fix')
                    )
                    .min(1)
                    .max(todayReportsKeyClausesCreateBodyRequestsItemRolesMax)
                    .describe('The roles to look for in this text: problem, cause or fix. Repeated roles count once.'),
            })
        )
        .max(todayReportsKeyClausesCreateBodyRequestsMax)
        .describe('The texts to mark, at most 3.'),
})
