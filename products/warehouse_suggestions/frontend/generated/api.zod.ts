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

export const warehouseSuggestionsAcceptCreateBodyRefreshIntervalSecondsMax = 2592000

export const warehouseSuggestionsAcceptCreateBodyLookbackSecondsMin = 0
export const warehouseSuggestionsAcceptCreateBodyLookbackSecondsMax = 2592000

export const WarehouseSuggestionsAcceptCreateBody = /* @__PURE__ */ zod.object({
    refresh_interval_seconds: zod
        .number()
        .min(1)
        .max(warehouseSuggestionsAcceptCreateBodyRefreshIntervalSecondsMax)
        .optional()
        .describe(
            'Materialize only: refresh interval to use instead of the proposed one, in seconds. Omit to keep the proposed interval.'
        ),
    refresh_mode: zod
        .enum(['full', 'incremental'])
        .describe('\* `full` - Full\n\* `incremental` - Incremental')
        .optional()
        .describe(
            'Materialize only: incremental or full, instead of the proposed refresh_mode. Omit to keep the proposed one. Switching to incremental needs incremental_key and unique_key when the payload has none.\n\n\* `full` - Full\n\* `incremental` - Incremental'
        ),
    incremental_key: zod
        .string()
        .optional()
        .describe(
            'Materialize only, incremental refresh only: an output column whose value only grows as rows arrive, such as a date, a datetime or an increasing number, instead of the proposed one. view-check-incremental lists the columns that qualify. Omit to keep the proposed key.'
        ),
    unique_key: zod
        .array(zod.string())
        .optional()
        .describe(
            'Materialize only, incremental refresh only: output columns that identify a row, instead of the proposed ones. Must include every GROUP BY column. Omit to keep the proposed key.'
        ),
    lookback_seconds: zod
        .number()
        .min(warehouseSuggestionsAcceptCreateBodyLookbackSecondsMin)
        .max(warehouseSuggestionsAcceptCreateBodyLookbackSecondsMax)
        .optional()
        .describe(
            "Materialize only, incremental refresh only: how far before the last refresh's highest incremental_key value each refresh reads again, in seconds, so late rows are picked up. Omit to keep the proposed lookback."
        ),
    keep_materialized: zod
        .boolean()
        .optional()
        .describe(
            "Deprecate only: true to keep a materialized view refreshing after it is deprecated. By default, accepting a deprecate suggestion also stops the view's refreshes and deletes its stored table, unless other views or syncs depend on it."
        ),
})

export const warehouseSuggestionsDismissCreateBodyNoteMax = 1000

export const WarehouseSuggestionsDismissCreateBody = /* @__PURE__ */ zod.object({
    reason: zod
        .enum(['not_useful', 'not_now', 'other'])
        .describe('\* `not_useful` - Not useful\n\* `not_now` - Not now\n\* `other` - Other')
        .describe(
            'Why the suggestion is dismissed.\n\n\* `not_useful` - Not useful\n\* `not_now` - Not now\n\* `other` - Other'
        ),
    note: zod
        .string()
        .max(warehouseSuggestionsDismissCreateBodyNoteMax)
        .optional()
        .describe('Optional note about the dismissal.'),
})
