/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 1 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Lists this project's ingestion warnings — events or person/group updates that were ingested with problems (oversized messages, rejected person merges, invalid data) — grouped by warning type. Each entry carries the warning's category and severity, the total count and a sparkline over the requested time range, and the most recent sample warnings with the affected event/person/group. Filter by category, type, severity or time range to drill into a specific problem.
 * @summary List ingestion warnings
 */
export const IngestionWarningsV2ListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ingestionWarningsV2ListQueryLimitMax = 500

export const ingestionWarningsV2ListQuerySamplesMax = 50

export const IngestionWarningsV2ListQueryParams = /* @__PURE__ */ zod.object({
    category: zod
        .string()
        .min(1)
        .optional()
        .describe(
            "Only return warnings in this category (e.g. 'size', 'merge', 'event'). Warnings from producers that don't yet emit a category have category 'unknown'."
        ),
    limit: zod
        .number()
        .min(1)
        .max(ingestionWarningsV2ListQueryLimitMax)
        .optional()
        .describe('Maximum number of warning types to return (default 100).'),
    order_by: zod
        .enum(['count', 'last_seen'])
        .optional()
        .describe(
            "Sort order for warning types: 'count' (most frequent first, the default) or 'last_seen' (most recent first).\n\n* `count` - count\n* `last_seen` - last_seen"
        ),
    q: zod
        .string()
        .min(1)
        .optional()
        .describe(
            'Only return warnings whose type or details contain this substring (case-sensitive). Useful for finding warnings about a specific distinct ID, event or property.'
        ),
    samples: zod
        .number()
        .min(1)
        .max(ingestionWarningsV2ListQuerySamplesMax)
        .optional()
        .describe('Maximum number of recent sample warnings to return per warning type (default 5).'),
    severity: zod
        .enum(['info', 'warning', 'error'])
        .optional()
        .describe(
            "Only return warnings with this severity. Warnings from producers that don't yet emit a severity have severity 'warning'.\n\n* `info` - info\n* `warning` - warning\n* `error` - error"
        ),
    since: zod
        .string()
        .min(1)
        .optional()
        .describe(
            "Start of the time range, as an ISO 8601 datetime (e.g. '2026-07-01T00:00:00Z') or a relative duration (e.g. '-24h', '-7d'). Defaults to 24 hours ago. Warnings are retained for 90 days."
        ),
    type: zod
        .string()
        .min(1)
        .optional()
        .describe(
            "Only return warnings of this type (e.g. 'message_size_too_large', 'cannot_merge_already_identified')."
        ),
    until: zod
        .string()
        .min(1)
        .optional()
        .describe(
            "End of the time range, as an ISO 8601 datetime or a relative duration (e.g. '-1h'). Defaults to now."
        ),
})
