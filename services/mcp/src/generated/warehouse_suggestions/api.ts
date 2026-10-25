/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 7 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const WarehouseSuggestionsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const WarehouseSuggestionsListQueryParams = () => zod.object({
    kind: zod
        .enum(['certify', 'deprecate', 'materialize', 'sql_repair', 'unmaterialize'])
        .optional()
        .describe(
            'Only return suggestions of this kind.\n\n\* `certify` - Certify\n\* `deprecate` - Deprecate\n\* `materialize` - Materialize\n\* `sql_repair` - SQL repair\n\* `unmaterialize` - Unmaterialize'
        ),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    status: zod
        .enum(['proposed', 'accepted', 'dismissed', 'expired', 'auto_resolved'])
        .optional()
        .describe(
            'Only return suggestions in this status.\n\n\* `proposed` - Proposed\n\* `accepted` - Accepted\n\* `dismissed` - Dismissed\n\* `expired` - Expired\n\* `auto_resolved` - Auto-resolved'
        ),
    subject_id: zod.string().optional().describe('Only return suggestions about the view or table with this ID.'),
})

export const warehouseSuggestionsRetrievePathIdRegExp = new RegExp(
    '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
)

export const WarehouseSuggestionsRetrieveParams = () => zod.object({
    id: zod.string().regex(warehouseSuggestionsRetrievePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const warehouseSuggestionsAcceptCreatePathIdRegExp = new RegExp(
    '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
)

export const WarehouseSuggestionsAcceptCreateParams = () => zod.object({
    id: zod.string().regex(warehouseSuggestionsAcceptCreatePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const warehouseSuggestionsAcceptCreateBodyRefreshIntervalSecondsMax = 2592000

export const warehouseSuggestionsAcceptCreateBodyLookbackSecondsMin = 0
export const warehouseSuggestionsAcceptCreateBodyLookbackSecondsMax = 2592000

export const WarehouseSuggestionsAcceptCreateBody = () => zod.object({
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

export const warehouseSuggestionsDismissCreatePathIdRegExp = new RegExp(
    '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
)

export const WarehouseSuggestionsDismissCreateParams = () => zod.object({
    id: zod.string().regex(warehouseSuggestionsDismissCreatePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const warehouseSuggestionsDismissCreateBodyNoteMax = 1000

export const WarehouseSuggestionsDismissCreateBody = () => zod.object({
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

export const warehouseSuggestionsResumeCreatePathIdRegExp = new RegExp(
    '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
)

export const WarehouseSuggestionsResumeCreateParams = () => zod.object({
    id: zod.string().regex(warehouseSuggestionsResumeCreatePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const WarehouseSuggestionsSqlRepairCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const warehouseSuggestionsSqlRepairCreateBodyProposedQueryMax = 100000

export const warehouseSuggestionsSqlRepairCreateBodyFailureEvidenceMax = 4000

export const warehouseSuggestionsSqlRepairCreateBodyReasonMax = 2000

export const warehouseSuggestionsSqlRepairCreateBodyExpectedEffectMax = 2000

export const WarehouseSuggestionsSqlRepairCreateBody = () => zod.object({
    saved_query_id: zod.string().describe('Saved view in this project that needs a SQL repair.'),
    proposed_query: zod
        .string()
        .max(warehouseSuggestionsSqlRepairCreateBodyProposedQueryMax)
        .describe('Complete proposed HogQL SELECT query. This operation validates it but does not apply it.'),
    failure_evidence: zod
        .string()
        .max(warehouseSuggestionsSqlRepairCreateBodyFailureEvidenceMax)
        .describe('Short failure evidence for the customer. Do not include secrets or query result data.'),
    reason: zod
        .string()
        .max(warehouseSuggestionsSqlRepairCreateBodyReasonMax)
        .describe('Why the proposed SQL can repair the failure.'),
    expected_effect: zod
        .string()
        .max(warehouseSuggestionsSqlRepairCreateBodyExpectedEffectMax)
        .describe('Expected result if the customer accepts the repair. Do not claim business equivalence.'),
})

export const WarehouseSuggestionsStatusRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})
