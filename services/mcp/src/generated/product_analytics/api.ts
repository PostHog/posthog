/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 15 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Returns the events retention period that every project without its own period uses, the default period while none is set, and the periods an organization admin can set.
 * @summary Get the organization's events retention period
 */
export const OrganizationEventsRetentionRetrieveParams = () => zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

/**
 * Sets how long every project without its own period keeps events. The period has to be one of retention_months_choices. Older events are deleted at the next monthly cleanup and can't be restored. Organization admins only.
 * @summary Set the organization's events retention period
 */
export const OrganizationEventsRetentionUpdateParams = () => zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const OrganizationEventsRetentionUpdateBody = () => zod.object({
    retention_months: zod
        .union([
            zod
                .union([
                    zod.literal(1),
                    zod.literal(3),
                    zod.literal(12),
                    zod.literal(24),
                    zod.literal(36),
                    zod.literal(60),
                    zod.literal(84),
                ])
                .describe(
                    '\* `1` - 1 month\n\* `3` - 3 months\n\* `12` - 1 year\n\* `24` - 2 years\n\* `36` - 3 years\n\* `60` - 5 years\n\* `84` - 7 years'
                ),
            zod.null(),
        ])
        .describe(
            "The period in months. It also has to be between min_retention_months and max_retention_months. A shorter period deletes older events, and deleted events can't be restored. Null removes the period.\n\n\* `1` - 1 month\n\* `3` - 3 months\n\* `12` - 1 year\n\* `24` - 2 years\n\* `36` - 3 years\n\* `60` - 5 years\n\* `84` - 7 years"
        ),
})

/**
 * Counts the events that the next monthly cleanup deletes if the organization keeps events for retention_months, summed over the projects without their own period. Organization admins only.
 * @summary Count the events the organization's period would delete
 */
export const OrganizationEventsRetentionDeletionCountParams = () => zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const organizationEventsRetentionDeletionCountQueryRetentionMonthsMax = 1200

export const OrganizationEventsRetentionDeletionCountQueryParams = () => zod.object({
    retention_months: zod
        .number()
        .min(1)
        .max(organizationEventsRetentionDeletionCountQueryRetentionMonthsMax)
        .describe('The period in months to count for, at most 1200. Only events older than this period are counted.'),
})

/**
 * Counts of $autocapture, $rageclick, and $dead_click events grouped by the element chain
 * they occurred on, ordered by count. Defaults to all three event types; narrow with the
 * include parameter.
 */
export const ElementsStatsRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ElementsStatsRetrieveQueryParams = () => zod.object({
    data_attributes: zod
        .string()
        .optional()
        .describe(
            "Comma-separated data attribute names (wildcards allowed, e.g. data-\*). When provided, each element's attributes map is filtered to matching attr__\* keys, shrinking the response."
        ),
    date_from: zod
        .string()
        .optional()
        .describe('Start of the date range (e.g. -7d, 2024-01-01). Defaults to last 7 days.'),
    date_to: zod.string().optional().describe('End of the date range (e.g. 2024-01-31). Defaults to now.'),
    filter_test_accounts: zod
        .boolean()
        .optional()
        .describe(
            "When true, applies the project's internal-and-test-account filters to the underlying events. Pass the lowercase string true; other truthy spellings are ignored."
        ),
    include: zod
        .array(zod.string())
        .optional()
        .describe(
            'Event types to include: $autocapture, $rageclick, $dead_click. Defaults to all three. Accepts repeated parameters, a JSON array, or a comma-separated list.'
        ),
    limit: zod.number().optional().describe('Maximum rows per page'),
    offset: zod.number().optional().describe('Pagination offset'),
    properties: zod
        .string()
        .optional()
        .describe(
            'JSON-encoded list of property filters to apply to the underlying events, e.g. [{\"key\": \"$current_url\", \"value\": \"https:\/\/example.com\/page\"}] or [{\"key\": \"email\", \"value\": \"@posthog.com\", \"operator\": \"icontains\", \"type\": \"person\"}]. Supports event, person, cohort, and element property filter types.'
        ),
    sampling_factor: zod.number().optional().describe('Sampling factor between 0 and 1'),
})

/**
 * Returns how far back events stay queryable for this project, the periods set for the project and its organization, the periods an admin can set, and the project's next deletion. Both queryable period fields are null while no retention period applies to the project.
 * @summary Get the events retention period for a project
 */
export const EventsRetentionRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Sets how long this project keeps events, overriding the organization's period. The period has to be one of retention_months_choices. Older events are deleted at the next monthly cleanup and can't be restored. Organization admins only.
 * @summary Set the events retention period for a project
 */
export const EventsRetentionUpdateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const EventsRetentionUpdateBody = () => zod.object({
    retention_months: zod
        .union([
            zod
                .union([
                    zod.literal(1),
                    zod.literal(3),
                    zod.literal(12),
                    zod.literal(24),
                    zod.literal(36),
                    zod.literal(60),
                    zod.literal(84),
                ])
                .describe(
                    '\* `1` - 1 month\n\* `3` - 3 months\n\* `12` - 1 year\n\* `24` - 2 years\n\* `36` - 3 years\n\* `60` - 5 years\n\* `84` - 7 years'
                ),
            zod.null(),
        ])
        .describe(
            "The period in months. It also has to be between min_retention_months and max_retention_months. A shorter period deletes older events, and deleted events can't be restored. Null removes the period.\n\n\* `1` - 1 month\n\* `3` - 3 months\n\* `12` - 1 year\n\* `24` - 2 years\n\* `36` - 3 years\n\* `60` - 5 years\n\* `84` - 7 years"
        ),
})

/**
 * Counts the project's events that the next monthly cleanup deletes if the project keeps events for retention_months. Organization admins only.
 * @summary Count the events a project's period would delete
 */
export const EventsRetentionDeletionCountParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const eventsRetentionDeletionCountQueryRetentionMonthsMax = 1200

export const EventsRetentionDeletionCountQueryParams = () => zod.object({
    retention_months: zod
        .number()
        .min(1)
        .max(eventsRetentionDeletionCountQueryRetentionMonthsMax)
        .describe('The period in months to count for, at most 1200. Only events older than this period are counted.'),
})

export const InsightsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const insightsListQueryRefreshDefault = `force_cache`

export const InsightsListQueryParams = () => zod.object({
    basic: zod.boolean().optional().describe('Return basic insight metadata only (no results, faster).'),
    created_by: zod
        .string()
        .optional()
        .describe(
            'JSON-encoded array of user IDs. Only returns insights whose `created_by` is in the list, e.g. `[1,42]`.'
        ),
    created_date_from: zod
        .string()
        .optional()
        .describe('Filter by `created_at > created_date_from`. Accepts absolute or relative dates.'),
    created_date_to: zod
        .string()
        .optional()
        .describe('Filter by `created_at < created_date_to`. Accepts absolute or relative dates.'),
    dashboards: zod
        .string()
        .optional()
        .describe('JSON-encoded array of dashboard IDs. Returns insights attached to every listed dashboard (AND).'),
    date_from: zod
        .string()
        .optional()
        .describe(
            'Filter by `last_modified_at > date_from`. Accepts absolute dates (`2025-04-23`) or relative strings (`-7d`, `-1m`).'
        ),
    date_to: zod
        .string()
        .optional()
        .describe('Filter by `last_modified_at < date_to`. Accepts absolute dates or relative strings.'),
    display: zod
        .string()
        .optional()
        .describe(
            'Comma-separated chart types, e.g. `ActionsLineGraph,ActionsBar`. Only returns trends and SQL insights shown as one of them. A trends insight with no chart type set counts as `ActionsLineGraph`.'
        ),
    exclude_bi: zod.boolean().optional().describe('Exclude Business intelligence worksheets from the insight list.'),
    favorited: zod
        .boolean()
        .optional()
        .describe('Include this parameter (any value) to restrict results to insights marked as favorited.'),
    format: zod.enum(['csv', 'json']).optional(),
    include_dashboards: zod
        .boolean()
        .optional()
        .describe(
            'Opt in to receiving the deprecated `dashboards` field in insight payloads. Once opt-in enforcement is enabled, API-token callers stop receiving it by default; use `dashboard_tiles` instead.'
        ),
    insight: zod
        .enum(['BI', 'FUNNELS', 'JOURNEYS', 'JSON', 'LIFECYCLE', 'PATHS', 'RETENTION', 'SQL', 'STICKINESS', 'TRENDS'])
        .optional()
        .describe(
            'Restrict to a single insight type. `JSON` matches non-wrapper query insights; `SQL` matches HogQL queries; `BI` matches editable worksheets.'
        ),
    last_viewed_date_from: zod
        .string()
        .optional()
        .describe('Filter by `last_viewed_at > last_viewed_date_from`. Accepts absolute or relative dates.'),
    last_viewed_date_to: zod
        .string()
        .optional()
        .describe('Filter by `last_viewed_at < last_viewed_date_to`. Accepts absolute or relative dates.'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    order: zod
        .string()
        .optional()
        .describe(
            'Sort by an insight field, with a leading minus for descending order. Supports last_modified_at and last_viewed_at.'
        ),
    refresh: zod
        .enum([
            'async',
            'async_except_on_cache_miss',
            'blocking',
            'force_async',
            'force_blocking',
            'force_cache',
            'lazy_async',
        ])
        .default(insightsListQueryRefreshDefault)
        .describe(
            "\nWhether to refresh the retrieved insights, how aggressively, and if sync or async:\n- `'force_cache'` - return cached data or a cache miss; always completes immediately as it never calculates\n- `'blocking'` - calculate synchronously (returning only when the query is done), UNLESS there are very fresh results in the cache\n- `'async'` - kick off background calculation (returning immediately with a query status), UNLESS there are very fresh results in the cache\n- `'lazy_async'` - kick off background calculation, UNLESS there are somewhat fresh results in the cache\n- `'force_blocking'` - calculate synchronously, even if fresh results are already cached\n- `'force_async'` - kick off background calculation, even if fresh results are already cached\nBackground calculation can be tracked using the `query_status` response field."
        ),
    saved: zod
        .boolean()
        .optional()
        .describe(
            'When truthy, restricts results to insights that are saved (or attached to a visible dashboard). When falsy, only unsaved insights.'
        ),
    search: zod
        .string()
        .optional()
        .describe(
            "Search term matched across name, derived_name, description, and tag names. Returns exact (case-insensitive substring) matches only; if no exact match exists, returns similar (fuzzy trigram) matches instead. Each result's `search_match_type` is `exact` or `similar`."
        ),
    short_id: zod.string().optional(),
    tags: zod
        .string()
        .optional()
        .describe('JSON-encoded array of tag names. Returns insights with any of the listed tags.'),
    user: zod
        .boolean()
        .optional()
        .describe(
            'Include this parameter (any value) to restrict results to insights created by the authenticated user.'
        ),
})

export const InsightsCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const InsightsCreateQueryParams = () => zod.object({
    format: zod.enum(['csv', 'json']).optional(),
    include_dashboards: zod
        .boolean()
        .optional()
        .describe(
            'Opt in to receiving the deprecated `dashboards` field in insight payloads. Once opt-in enforcement is enabled, API-token callers stop receiving it by default; use `dashboard_tiles` instead.'
        ),
})

export const insightsCreateBodyNameMax = 400

export const insightsCreateBodyDerivedNameMax = 400

export const insightsCreateBodyOrderMin = -2147483648
export const insightsCreateBodyOrderMax = 2147483647

export const insightsCreateBodyDescriptionMax = 400

export const InsightsCreateBody = () => zod
    .object({
        name: zod.string().max(insightsCreateBodyNameMax).nullish(),
        derived_name: zod.string().max(insightsCreateBodyDerivedNameMax).nullish(),
        order: zod.number().min(insightsCreateBodyOrderMin).max(insightsCreateBodyOrderMax).nullish(),
        deleted: zod.boolean().optional(),
        dashboards: zod
            .array(zod.number())
            .optional()
            .describe(
                '\n        DEPRECATED. Will be removed in a future release. Use dashboard_tiles instead.\n        A dashboard ID for each of the dashboards that this insight is displayed on.\n        This field is omitted from session-authenticated responses unless `include_dashboards=true`\n        is passed. Once opt-in enforcement is enabled, API-token callers (personal API keys, OAuth)\n        must opt in the same way. Do not rely on it being present.\n        '
            ),
        description: zod.string().max(insightsCreateBodyDescriptionMax).nullish(),
        tags: zod.array(zod.unknown()).optional(),
        favorited: zod.boolean().optional(),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Simplified serializer to speed response times when loading large amounts of objects.')

export const InsightsRetrieveParams = () => zod.object({
    id: zod
        .union([zod.number(), zod.string()])
        .describe('Numeric primary key or 8-character `short_id` (for example `AaVQ8Ijw`) identifying the insight.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const insightsRetrieveQueryRefreshDefault = `force_cache`

export const InsightsRetrieveQueryParams = () => zod.object({
    filters_override: zod
        .string()
        .optional()
        .describe(
            "Object (or pre-encoded JSON string) to override the insight's filters for this request only (not persisted). Top-level keys replace; nested values are not deep-merged — pass the complete value for any key you override. Accepts the same keys as the dashboard filters schema (e.g., `date_from`, `date_to`, `properties`). Ignored when accessed via a sharing token."
        ),
    format: zod.enum(['csv', 'json']).optional(),
    from_dashboard: zod
        .number()
        .optional()
        .describe(
            "\nOnly if loading an insight in the context of a dashboard: The relevant dashboard's ID.\nWhen set, the specified dashboard's filters and date range override will be applied."
        ),
    include_dashboards: zod
        .boolean()
        .optional()
        .describe(
            'Opt in to receiving the deprecated `dashboards` field in insight payloads. Once opt-in enforcement is enabled, API-token callers stop receiving it by default; use `dashboard_tiles` instead.'
        ),
    refresh: zod
        .enum([
            'async',
            'async_except_on_cache_miss',
            'blocking',
            'force_async',
            'force_blocking',
            'force_cache',
            'lazy_async',
        ])
        .default(insightsRetrieveQueryRefreshDefault)
        .describe(
            "\nWhether to refresh the insight, how aggresively, and if sync or async:\n- `'force_cache'` - return cached data or a cache miss; always completes immediately as it never calculates\n- `'blocking'` - calculate synchronously (returning only when the query is done), UNLESS there are very fresh results in the cache\n- `'async'` - kick off background calculation (returning immediately with a query status), UNLESS there are very fresh results in the cache\n- `'lazy_async'` - kick off background calculation, UNLESS there are somewhat fresh results in the cache\n- `'force_blocking'` - calculate synchronously, even if fresh results are already cached\n- `'force_async'` - kick off background calculation, even if fresh results are already cached\nBackground calculation can be tracked using the `query_status` response field."
        ),
    variables_override: zod
        .string()
        .optional()
        .describe(
            'Object (or pre-encoded JSON string) to override the insight\'s HogQL variables for this request only (not persisted). Format: {\"<variable_id>\": {\"code_name\": \"<code_name>\", \"variableId\": \"<variable_id>\", \"value\": <new_value>}}. Each entry must include `code_name` — partial entries are silently dropped. The simplest workflow is to call `insight-get` first, copy the matching entry from the response, and mutate `value`. Top-level keys replace; nested values are not deep-merged. Ignored when accessed via a sharing token.'
        ),
})

export const InsightsPartialUpdateParams = () => zod.object({
    id: zod
        .union([zod.number(), zod.string()])
        .describe('Numeric primary key or 8-character `short_id` (for example `AaVQ8Ijw`) identifying the insight.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const InsightsPartialUpdateQueryParams = () => zod.object({
    format: zod.enum(['csv', 'json']).optional(),
    include_dashboards: zod
        .boolean()
        .optional()
        .describe(
            'Opt in to receiving the deprecated `dashboards` field in insight payloads. Once opt-in enforcement is enabled, API-token callers stop receiving it by default; use `dashboard_tiles` instead.'
        ),
})

export const insightsPartialUpdateBodyNameMax = 400

export const insightsPartialUpdateBodyDerivedNameMax = 400

export const insightsPartialUpdateBodyOrderMin = -2147483648
export const insightsPartialUpdateBodyOrderMax = 2147483647

export const insightsPartialUpdateBodyDescriptionMax = 400

export const InsightsPartialUpdateBody = () => zod
    .object({
        name: zod.string().max(insightsPartialUpdateBodyNameMax).nullish(),
        derived_name: zod.string().max(insightsPartialUpdateBodyDerivedNameMax).nullish(),
        order: zod.number().min(insightsPartialUpdateBodyOrderMin).max(insightsPartialUpdateBodyOrderMax).nullish(),
        deleted: zod.boolean().optional(),
        dashboards: zod
            .array(zod.number())
            .optional()
            .describe(
                '\n        DEPRECATED. Will be removed in a future release. Use dashboard_tiles instead.\n        A dashboard ID for each of the dashboards that this insight is displayed on.\n        This field is omitted from session-authenticated responses unless `include_dashboards=true`\n        is passed. Once opt-in enforcement is enabled, API-token callers (personal API keys, OAuth)\n        must opt in the same way. Do not rely on it being present.\n        '
            ),
        description: zod.string().max(insightsPartialUpdateBodyDescriptionMax).nullish(),
        tags: zod.array(zod.unknown()).optional(),
        favorited: zod.boolean().optional(),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Simplified serializer to speed response times when loading large amounts of objects.')

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const InsightsDestroyParams = () => zod.object({
    id: zod
        .union([zod.number(), zod.string()])
        .describe('Numeric primary key or 8-character `short_id` (for example `AaVQ8Ijw`) identifying the insight.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const InsightsDestroyQueryParams = () => zod.object({
    format: zod.enum(['csv', 'json']).optional(),
})

/**
 * Audit trail for a single insight — every change made to it, by whom, and when. Use this when you want the change history of a specific insight; use the project-wide activity endpoint for a broader view.
 */
export const InsightsActivityRetrieveParams = () => zod.object({
    id: zod.number().describe('A unique integer value identifying this insight.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const InsightsActivityRetrieveQueryParams = () => zod.object({
    format: zod.enum(['csv', 'json']).optional(),
    limit: zod.number().optional().describe('Page size. Defaults to 10.'),
    page: zod.number().optional().describe('1-indexed page number. Defaults to 1.'),
})

/**
 * Project-wide audit trail across all insights — who created, edited, deleted, or restored insights, what changed (with before/after diffs), and when. Useful for surfacing what people (or agents) have been working on recently.
 */
export const InsightsAllActivityRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const InsightsAllActivityRetrieveQueryParams = () => zod.object({
    format: zod.enum(['csv', 'json']).optional(),
    limit: zod.number().optional().describe('Page size. Defaults to 10.'),
    page: zod.number().optional().describe('1-indexed page number. Defaults to 1.'),
})

/**
 * Returns insights ranked by view count over the last N days (default 7), highest first. Each result includes the same metadata as the standard insights list, plus a `view_count` and up to 3 recent `viewers`. Useful for surfacing the most-used insights in a project.
 */
export const InsightsTrendingRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const InsightsTrendingRetrieveQueryParams = () => zod.object({
    days: zod
        .number()
        .optional()
        .describe(
            "Time window in days to compute view counts over. Defaults to 7. Larger windows surface consistently popular insights; smaller windows surface what's hot right now."
        ),
    format: zod.enum(['csv', 'json']).optional(),
    include_dashboards: zod
        .boolean()
        .optional()
        .describe(
            'Opt in to receiving the deprecated `dashboards` field in insight payloads. Once opt-in enforcement is enabled, API-token callers stop receiving it by default; use `dashboard_tiles` instead.'
        ),
    limit: zod.number().optional().describe('Maximum number of insights to return. Defaults to 10. Capped at 100.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})
