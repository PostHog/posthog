/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 6 enabled ops
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
        .enum(['certify', 'deprecate', 'materialize'])
        .optional()
        .describe(
            'Only return suggestions of this kind.\n\n\* `certify` - Certify\n\* `deprecate` - Deprecate\n\* `materialize` - Materialize'
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

export const WarehouseSuggestionsAcceptCreateBody = () => zod.object({
    refresh_interval_seconds: zod
        .number()
        .min(1)
        .max(warehouseSuggestionsAcceptCreateBodyRefreshIntervalSecondsMax)
        .optional()
        .describe('Materialize only: refresh interval to use instead of the proposed one, in seconds.'),
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

export const WarehouseSuggestionsStatusRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})
