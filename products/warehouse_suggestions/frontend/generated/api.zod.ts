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
        .describe('Materialize only: refresh interval to use instead of the proposed one, in seconds.'),
    incremental_key: zod
        .string()
        .nullish()
        .describe(
            'Materialize only: replaces the suggested refresh mode. A date or datetime output column whose advancing value marks new rows, so each refresh reads only those rows. Send null to rebuild the whole table on each refresh instead. Omit to keep the suggested refresh mode.'
        ),
    unique_key: zod
        .array(zod.string())
        .optional()
        .describe(
            'Materialize only: output columns that identify a row, so a refresh updates rows instead of adding duplicates. Must include every GROUP BY column. Required when incremental_key is a column.'
        ),
    lookback_seconds: zod
        .number()
        .min(warehouseSuggestionsAcceptCreateBodyLookbackSecondsMin)
        .max(warehouseSuggestionsAcceptCreateBodyLookbackSecondsMax)
        .optional()
        .describe(
            "Materialize only: how far before the last refresh's highest incremental_key value to read again, so late rows are picked up. Defaults to 0."
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
