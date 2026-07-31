/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const userBasicApiDistinctIdMax = 200

export const userBasicApiFirstNameMax = 150

export const userBasicApiLastNameMax = 150

export const userBasicApiEmailMax = 254

export const UserBasicApi = zod.object({
    id: zod.number(),
    uuid: zod.uuid(),
    distinct_id: zod.string().max(userBasicApiDistinctIdMax).nullish(),
    first_name: zod.string().max(userBasicApiFirstNameMax).optional(),
    last_name: zod.string().max(userBasicApiLastNameMax).optional(),
    email: zod.email().max(userBasicApiEmailMax),
    is_email_verified: zod.boolean().nullish(),
    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
    role_at_organization: zod.union([RoleAtOrganizationEnumApi, BlankEnumApi, zod.null()]).optional(),
})

export type UserBasicApi = zod.input<typeof UserBasicApi>
export type UserBasicApiOutput = zod.output<typeof UserBasicApi>

export const EndpointMaterializationApi = zod
    .object({
        name: zod.string().describe('URL-safe endpoint name.'),
        status: zod.string().optional().describe("Current materialization status (e.g. 'Completed', 'Running')."),
        can_materialize: zod.boolean().describe('Whether this endpoint query can be materialized.'),
        reason: zod
            .string()
            .nullish()
            .describe('Reason why materialization is not possible (only when can_materialize is false).'),
        last_materialized_at: zod
            .string()
            .nullish()
            .describe('ISO 8601 timestamp of the last successful materialization.'),
        error: zod.string().optional().describe('Last materialization error message, if any.'),
        saved_query_id: zod
            .uuid()
            .nullish()
            .describe(
                'UUID of the underlying saved query backing this materialization. Only populated when the version is materialized.'
            ),
    })
    .describe('Materialization status for an endpoint version.')

export type EndpointMaterializationApi = zod.input<typeof EndpointMaterializationApi>
export type EndpointMaterializationApiOutput = zod.output<typeof EndpointMaterializationApi>

export const EndpointColumnApi = zod
    .object({
        name: zod.string().describe('Column name from the query SELECT clause.'),
        type: zod
            .string()
            .describe(
                'Serialized column type: integer, float, string, datetime, date, boolean, array, json, or unknown.'
            ),
    })
    .describe("A column in the endpoint's query result.")

export type EndpointColumnApi = zod.input<typeof EndpointColumnApi>
export type EndpointColumnApiOutput = zod.output<typeof EndpointColumnApi>

export const EndpointResponseApi = zod
    .object({
        id: zod.uuid().describe('Unique endpoint identifier (UUID).'),
        name: zod.string().describe('URL-safe endpoint name, unique per team.'),
        description: zod.string().nullable().describe('Human-readable description of the endpoint.'),
        query: zod.unknown().describe("The HogQL or insight query definition (JSON object with 'kind' key)."),
        is_active: zod.boolean().describe('Whether the endpoint can be executed via the API.'),
        data_freshness_seconds: zod
            .number()
            .describe('How fresh the data is, in seconds. One of: 900, 1800, 3600, 21600, 43200, 86400, 604800.'),
        endpoint_path: zod
            .string()
            .describe(
                'Relative API path to execute this endpoint (e.g. \/api\/projects\/{team_id}\/endpoints\/{name}\/run).'
            ),
        url: zod.string().nullable().describe('Absolute URL to execute this endpoint.'),
        ui_url: zod.string().nullable().describe('Absolute URL to view this endpoint in the PostHog UI.'),
        created_at: zod.iso.datetime({ offset: true }).describe('When the endpoint was created (ISO 8601).'),
        updated_at: zod.iso.datetime({ offset: true }).describe('When the endpoint was last updated (ISO 8601).'),
        created_by: UserBasicApi.describe('User who created the endpoint.'),
        is_materialized: zod.boolean().describe("Whether the current version's results are pre-computed to S3."),
        current_version: zod.number().describe('Latest version number.'),
        current_version_id: zod.uuid().nullish().describe('UUID of the current EndpointVersion row.'),
        versions_count: zod.number().describe('Total number of versions for this endpoint.'),
        derived_from_insight: zod.string().nullable().describe('Short ID of the source insight, if derived from one.'),
        last_executed_at: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe('When this endpoint was last executed via the API (ISO 8601), or null if never executed.'),
        materialization: EndpointMaterializationApi.describe(
            'Materialization status and configuration for the current version.'
        ),
        bucket_overrides: zod
            .record(zod.string(), zod.unknown())
            .nullable()
            .describe('Per-column bucket overrides for range variable materialization.'),
        columns: zod.array(EndpointColumnApi).describe("Column names and types from the query's SELECT clause."),
        tags: zod.array(zod.string()).describe('Tag names associated with this endpoint.'),
        optional_breakdown_properties: zod
            .array(zod.string())
            .describe(
                'Breakdown property names that may be omitted on \/run. Omitted ones return data aggregated across all values of that breakdown.'
            ),
    })
    .describe('Full endpoint representation returned by list\/retrieve\/create\/update.')

export type EndpointResponseApi = zod.input<typeof EndpointResponseApi>
export type EndpointResponseApiOutput = zod.output<typeof EndpointResponseApi>

export const PaginatedEndpointResponseListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(EndpointResponseApi),
})

export type PaginatedEndpointResponseListApi = zod.input<typeof PaginatedEndpointResponseListApi>
export type PaginatedEndpointResponseListApiOutput = zod.output<typeof PaginatedEndpointResponseListApi>

export const EndpointRequestApi = zod
    .object({
        name: zod
            .string()
            .nullish()
            .describe(
                'Unique URL-safe name. Must start with a letter, only letters\/numbers\/hyphens\/underscores, max 128 chars.'
            ),
        query: zod
            .unknown()
            .optional()
            .describe('HogQL or insight query this endpoint executes. Changing this auto-creates a new version.'),
        description: zod.string().nullish().describe('Human-readable description of what this endpoint returns.'),
        data_freshness_seconds: zod
            .number()
            .nullish()
            .describe(
                'How fresh the data should be, in seconds. Must be one of: 900 (15 min), 1800 (30 min), 3600 (1 h), 21600 (6 h), 43200 (12 h), 86400 (24 h, default), 604800 (7 d). Controls cache TTL and materialization sync frequency.'
            ),
        is_active: zod.boolean().nullish().describe('Whether this endpoint is available for execution via the API.'),
        is_materialized: zod.boolean().nullish().describe('Whether query results are materialized to S3.'),
        derived_from_insight: zod
            .string()
            .nullish()
            .describe('Short ID of the insight this endpoint was derived from.'),
        version: zod
            .number()
            .nullish()
            .describe('Target a specific version for updates (defaults to current version).'),
        bucket_overrides: zod
            .record(zod.string(), zod.unknown())
            .nullish()
            .describe(
                'Per-column bucket overrides for range variable materialization. Keys are column names, values are bucket keys.'
            ),
        deleted: zod.boolean().nullish().describe('Set to true to soft-delete this endpoint.'),
        tags: zod
            .array(zod.string())
            .nullish()
            .describe('List of tag names to associate with this endpoint. Replaces any existing tags.'),
        optional_breakdown_properties: zod
            .array(zod.string())
            .nullish()
            .describe(
                'Breakdown property names that may be omitted on \/run. Omitted ones return data aggregated across all values of that breakdown. Defaults to [] — every breakdown variable is required.'
            ),
    })
    .describe('Schema for creating\/updating endpoints. OpenAPI docs only — validation uses Pydantic.')

export type EndpointRequestApi = zod.input<typeof EndpointRequestApi>
export type EndpointRequestApiOutput = zod.output<typeof EndpointRequestApi>

export const EndpointVersionResponseApi = zod
    .object({
        id: zod.uuid().describe('Unique endpoint identifier (UUID).'),
        name: zod.string().describe('URL-safe endpoint name, unique per team.'),
        description: zod.string().nullable().describe('Human-readable description of the endpoint.'),
        query: zod.unknown().describe("The HogQL or insight query definition (JSON object with 'kind' key)."),
        is_active: zod.boolean().describe('Whether the endpoint can be executed via the API.'),
        data_freshness_seconds: zod
            .number()
            .describe('How fresh the data is, in seconds. One of: 900, 1800, 3600, 21600, 43200, 86400, 604800.'),
        endpoint_path: zod
            .string()
            .describe(
                'Relative API path to execute this endpoint (e.g. \/api\/projects\/{team_id}\/endpoints\/{name}\/run).'
            ),
        url: zod.string().nullable().describe('Absolute URL to execute this endpoint.'),
        ui_url: zod.string().nullable().describe('Absolute URL to view this endpoint in the PostHog UI.'),
        created_at: zod.iso.datetime({ offset: true }).describe('When the endpoint was created (ISO 8601).'),
        updated_at: zod.iso.datetime({ offset: true }).describe('When the endpoint was last updated (ISO 8601).'),
        created_by: UserBasicApi.describe('User who created the endpoint.'),
        is_materialized: zod.boolean().describe("Whether the current version's results are pre-computed to S3."),
        current_version: zod.number().describe('Latest version number.'),
        current_version_id: zod.uuid().nullish().describe('UUID of the current EndpointVersion row.'),
        versions_count: zod.number().describe('Total number of versions for this endpoint.'),
        derived_from_insight: zod.string().nullable().describe('Short ID of the source insight, if derived from one.'),
        last_executed_at: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe(
                "When this specific version was last executed via the API (ISO 8601), or null if it hasn't been executed. Per-version tracking is recent, so versions that predate it read null until their next run."
            ),
        materialization: EndpointMaterializationApi.describe(
            'Materialization status and configuration for the current version.'
        ),
        bucket_overrides: zod
            .record(zod.string(), zod.unknown())
            .nullable()
            .describe('Per-column bucket overrides for range variable materialization.'),
        columns: zod.array(EndpointColumnApi).describe("Column names and types from the query's SELECT clause."),
        tags: zod.array(zod.string()).describe('Tag names associated with this endpoint.'),
        optional_breakdown_properties: zod
            .array(zod.string())
            .describe(
                'Breakdown property names that may be omitted on \/run. Omitted ones return data aggregated across all values of that breakdown.'
            ),
        version: zod.number().describe('Version number.'),
        version_id: zod.uuid().describe('Version unique identifier (UUID).'),
        endpoint_is_active: zod
            .boolean()
            .describe('Whether the parent endpoint is active (distinct from version.is_active).'),
        version_created_at: zod.string().describe('ISO 8601 timestamp when this version was created.'),
        version_updated_at: zod.string().nullable().describe('ISO 8601 timestamp when this version was last updated.'),
        version_created_by: zod.union([UserBasicApi, zod.null()]).describe('User who created this version.'),
    })
    .describe('Extended endpoint representation when viewing a specific version.')

export type EndpointVersionResponseApi = zod.input<typeof EndpointVersionResponseApi>
export type EndpointVersionResponseApiOutput = zod.output<typeof EndpointVersionResponseApi>

export const PatchedEndpointRequestApi = zod
    .object({
        name: zod
            .string()
            .nullish()
            .describe(
                'Unique URL-safe name. Must start with a letter, only letters\/numbers\/hyphens\/underscores, max 128 chars.'
            ),
        query: zod
            .unknown()
            .optional()
            .describe('HogQL or insight query this endpoint executes. Changing this auto-creates a new version.'),
        description: zod.string().nullish().describe('Human-readable description of what this endpoint returns.'),
        data_freshness_seconds: zod
            .number()
            .nullish()
            .describe(
                'How fresh the data should be, in seconds. Must be one of: 900 (15 min), 1800 (30 min), 3600 (1 h), 21600 (6 h), 43200 (12 h), 86400 (24 h, default), 604800 (7 d). Controls cache TTL and materialization sync frequency.'
            ),
        is_active: zod.boolean().nullish().describe('Whether this endpoint is available for execution via the API.'),
        is_materialized: zod.boolean().nullish().describe('Whether query results are materialized to S3.'),
        derived_from_insight: zod
            .string()
            .nullish()
            .describe('Short ID of the insight this endpoint was derived from.'),
        version: zod
            .number()
            .nullish()
            .describe('Target a specific version for updates (defaults to current version).'),
        bucket_overrides: zod
            .record(zod.string(), zod.unknown())
            .nullish()
            .describe(
                'Per-column bucket overrides for range variable materialization. Keys are column names, values are bucket keys.'
            ),
        deleted: zod.boolean().nullish().describe('Set to true to soft-delete this endpoint.'),
        tags: zod
            .array(zod.string())
            .nullish()
            .describe('List of tag names to associate with this endpoint. Replaces any existing tags.'),
        optional_breakdown_properties: zod
            .array(zod.string())
            .nullish()
            .describe(
                'Breakdown property names that may be omitted on \/run. Omitted ones return data aggregated across all values of that breakdown. Defaults to [] — every breakdown variable is required.'
            ),
    })
    .describe('Schema for creating\/updating endpoints. OpenAPI docs only — validation uses Pydantic.')

export type PatchedEndpointRequestApi = zod.input<typeof PatchedEndpointRequestApi>
export type PatchedEndpointRequestApiOutput = zod.output<typeof PatchedEndpointRequestApi>

export const MaterializationPreviewRequestApi = zod.object({
    version: zod.number().optional(),
    bucket_overrides: zod
        .record(zod.string(), zod.string())
        .nullish()
        .describe('Per-column bucket function overrides, e.g. {\"timestamp\": \"hour\"}'),
})

export type MaterializationPreviewRequestApi = zod.input<typeof MaterializationPreviewRequestApi>
export type MaterializationPreviewRequestApiOutput = zod.output<typeof MaterializationPreviewRequestApi>

export const EndpointMaterializationSuggestionRequestApi = zod
    .object({
        version: zod
            .number()
            .nullish()
            .describe('Endpoint version to suggest a fix for. Defaults to the latest version.'),
    })
    .describe('Request body for the AI materialization-fix suggestion action.')

export type EndpointMaterializationSuggestionRequestApi = zod.input<typeof EndpointMaterializationSuggestionRequestApi>
export type EndpointMaterializationSuggestionRequestApiOutput = zod.output<
    typeof EndpointMaterializationSuggestionRequestApi
>

export const SuggestionStatusEnumApi = zod
    .enum(['ok', 'cannot_fix', 'invalid', 'model_error'])
    .describe('\* `ok` - ok\n\* `cannot_fix` - cannot_fix\n\* `invalid` - invalid\n\* `model_error` - model_error')

export type SuggestionStatusEnumApi = zod.input<typeof SuggestionStatusEnumApi>
export type SuggestionStatusEnumApiOutput = zod.output<typeof SuggestionStatusEnumApi>

export const EndpointMaterializationSuggestionApi = zod
    .object({
        suggestion_status: SuggestionStatusEnumApi.describe(
            "Outcome of the suggestion run: 'ok' — the suggested query passes the live materialization checks; 'cannot_fix' — no semantically equivalent rewrite exists; 'invalid' — a suggestion was produced but never passed validation (suggested_query carries the last attempt); 'model_error' — the model returned no usable response.\n\n\* `ok` - ok\n\* `cannot_fix` - cannot_fix\n\* `invalid` - invalid\n\* `model_error` - model_error"
        ),
        suggested_query: zod
            .string()
            .nullable()
            .describe('The complete rewritten SQL query, or null when no rewrite was produced.'),
        explanation: zod
            .string()
            .nullable()
            .describe('User-facing explanation of what was changed and why, or why no fix exists.'),
        attempts: zod.number().describe('How many suggest→validate rounds were used.'),
        error: zod.string().nullable().describe('Last validation failure when the suggestion did not pass the checks.'),
        original_reason: zod.string().describe('The materialization blocker that triggered the suggestion.'),
    })
    .describe('AI-suggested query rewrite that would make the endpoint materializable.')

export type EndpointMaterializationSuggestionApi = zod.input<typeof EndpointMaterializationSuggestionApi>
export type EndpointMaterializationSuggestionApiOutput = zod.output<typeof EndpointMaterializationSuggestionApi>

export const EndpointRunResponseApi = zod
    .object({
        name: zod.string().describe('URL-safe endpoint name that was executed.'),
        execution_id: zod
            .uuid()
            .optional()
            .describe(
                "Unique identifier for this execution. Use it to find the matching entry in the endpoint's logs."
            ),
        results: zod
            .array(zod.unknown())
            .optional()
            .describe('Query result rows. Each row is a list of values matching the columns order.'),
        columns: zod.array(zod.string()).optional().describe('Column names from the query SELECT clause.'),
        hasMore: zod.boolean().optional().describe('Whether more results are available beyond the limit.'),
        endpoint_version: zod.number().optional().describe('Version number of the endpoint that was executed.'),
    })
    .describe('Response from executing an endpoint query.')

export type EndpointRunResponseApi = zod.input<typeof EndpointRunResponseApi>
export type EndpointRunResponseApiOutput = zod.output<typeof EndpointRunResponseApi>

export const EndpointRunRequestApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type EndpointRunRequestApi = zod.input<typeof EndpointRunRequestApi>
export type EndpointRunRequestApiOutput = zod.output<typeof EndpointRunRequestApi>

export const PaginatedEndpointVersionResponseListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(EndpointVersionResponseApi),
})

export type PaginatedEndpointVersionResponseListApi = zod.input<typeof PaginatedEndpointVersionResponseListApi>
export type PaginatedEndpointVersionResponseListApiOutput = zod.output<typeof PaginatedEndpointVersionResponseListApi>

export const EndpointLastExecutionTimesRequestApi = zod.object({
    names: zod.array(zod.string()),
})

export type EndpointLastExecutionTimesRequestApi = zod.input<typeof EndpointLastExecutionTimesRequestApi>
export type EndpointLastExecutionTimesRequestApiOutput = zod.output<typeof EndpointLastExecutionTimesRequestApi>

export const ClickhouseQueryProgressApi = zod.object({
    active_cpu_time: zod.number(),
    bytes_read: zod.number(),
    estimated_rows_total: zod.number(),
    rows_read: zod.number(),
    time_elapsed: zod.number(),
})

export type ClickhouseQueryProgressApi = zod.input<typeof ClickhouseQueryProgressApi>
export type ClickhouseQueryProgressApiOutput = zod.output<typeof ClickhouseQueryProgressApi>

export const queryStatusApiCompleteDefault = false
export const queryStatusApiErrorDefault = false
export const queryStatusApiQueryAsyncDefault = true

export const QueryStatusApi = zod.object({
    complete: zod
        .union([zod.boolean(), zod.null()])
        .default(queryStatusApiCompleteDefault)
        .describe(
            'Whether the query is still running. Will be true if the query is complete, even if it errored. Either result or error will be set.'
        ),
    dashboard_id: zod.union([zod.number(), zod.null()]).optional(),
    end_time: zod
        .union([zod.iso.datetime({ offset: true }), zod.null()])
        .optional()
        .describe('When did the query execution task finish (whether successfully or not).'),
    error: zod
        .union([zod.boolean(), zod.null()])
        .default(queryStatusApiErrorDefault)
        .describe(
            'If the query failed, this will be set to true. More information can be found in the error_message field.'
        ),
    error_code: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe('Stable machine-readable code for the error (the DRF exception code), when known.'),
    error_message: zod.union([zod.string(), zod.null()]).optional(),
    expiration_time: zod.union([zod.iso.datetime({ offset: true }), zod.null()]).optional(),
    id: zod.string(),
    insight_id: zod.union([zod.number(), zod.null()]).optional(),
    labels: zod.union([zod.array(zod.string()), zod.null()]).optional(),
    pickup_time: zod
        .union([zod.iso.datetime({ offset: true }), zod.null()])
        .optional()
        .describe('When was the query execution task picked up by a worker.'),
    query_async: zod.boolean().default(queryStatusApiQueryAsyncDefault).describe('ONLY async queries use QueryStatus.'),
    query_progress: zod.union([ClickhouseQueryProgressApi, zod.null()]).optional(),
    results: zod.unknown().optional(),
    start_time: zod
        .union([zod.iso.datetime({ offset: true }), zod.null()])
        .optional()
        .describe('When was query execution task enqueued.'),
    task_id: zod.union([zod.string(), zod.null()]).optional(),
    team_id: zod.number(),
})

export type QueryStatusApi = zod.input<typeof QueryStatusApi>
export type QueryStatusApiOutput = zod.output<typeof QueryStatusApi>

export const QueryStatusResponseApi = zod.object({
    query_status: QueryStatusApi,
})

export type QueryStatusResponseApi = zod.input<typeof QueryStatusResponseApi>
export type QueryStatusResponseApiOutput = zod.output<typeof QueryStatusResponseApi>

export const EndpointMaterializationConditionsApi = zod
    .object({
        conditions_source: zod
            .string()
            .describe(
                'Python source code of the checks that decide whether an endpoint query can be materialized, read from the running system — always matches what this instance enforces. Reason from it to rewrite a rejected query into a form that passes every check.'
            ),
        rewrite_contract: zod
            .string()
            .describe(
                'Hard rules a rewrite must obey so it stays semantically equivalent to the original query (same results for all variable values, keep every variable placeholder unchanged).'
            ),
    })
    .describe('The live materialization rules, for agents that want to rewrite a rejected query themselves.')

export type EndpointMaterializationConditionsApi = zod.input<typeof EndpointMaterializationConditionsApi>
export type EndpointMaterializationConditionsApiOutput = zod.output<typeof EndpointMaterializationConditionsApi>

export const DashboardFilterApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type DashboardFilterApi = zod.input<typeof DashboardFilterApi>
export type DashboardFilterApiOutput = zod.output<typeof DashboardFilterApi>

export const EndpointRefreshModeApi = zod.enum(['cache', 'force', 'direct'])

export type EndpointRefreshModeApi = zod.input<typeof EndpointRefreshModeApi>
export type EndpointRefreshModeApiOutput = zod.output<typeof EndpointRefreshModeApi>

export const BreakdownTypeApi = zod.enum([
    'cohort',
    'person',
    'event',
    'event_metadata',
    'group',
    'session',
    'hogql',
    'data_warehouse',
    'data_warehouse_person_property',
    'revenue_analytics',
])

export type BreakdownTypeApi = zod.input<typeof BreakdownTypeApi>
export type BreakdownTypeApiOutput = zod.output<typeof BreakdownTypeApi>

export const MultipleBreakdownTypeApi = zod.enum([
    'person',
    'event',
    'event_metadata',
    'group',
    'session',
    'hogql',
    'cohort',
    'revenue_analytics',
    'data_warehouse',
    'data_warehouse_person_property',
])

export type MultipleBreakdownTypeApi = zod.input<typeof MultipleBreakdownTypeApi>
export type MultipleBreakdownTypeApiOutput = zod.output<typeof MultipleBreakdownTypeApi>

export const BreakdownApi = zod.object({
    group_type_index: zod.union([zod.number(), zod.null()]).optional(),
    histogram_bin_count: zod.union([zod.number(), zod.null()]).optional(),
    normalize_url: zod.union([zod.boolean(), zod.null()]).optional(),
    property: zod.union([zod.string(), zod.number()]),
    type: zod.union([MultipleBreakdownTypeApi, zod.null()]).optional(),
})

export type BreakdownApi = zod.input<typeof BreakdownApi>
export type BreakdownApiOutput = zod.output<typeof BreakdownApi>

export const breakdownFilterApiBreakdownTypeDefault = `event`
export const breakdownFilterApiBreakdownsOneMax = 3

export const BreakdownFilterApi = zod.object({
    breakdown: zod
        .union([zod.string(), zod.array(zod.union([zod.string(), zod.number()])), zod.number(), zod.null()])
        .optional(),
    breakdown_group_type_index: zod.union([zod.number(), zod.null()]).optional(),
    breakdown_hide_other_aggregation: zod.union([zod.boolean(), zod.null()]).optional(),
    breakdown_histogram_bin_count: zod.union([zod.number(), zod.null()]).optional(),
    breakdown_limit: zod.union([zod.number(), zod.null()]).optional(),
    breakdown_normalize_url: zod.union([zod.boolean(), zod.null()]).optional(),
    breakdown_path_cleaning: zod.union([zod.boolean(), zod.null()]).optional(),
    breakdown_type: zod.union([BreakdownTypeApi, zod.null()]).default(breakdownFilterApiBreakdownTypeDefault),
    breakdowns: zod.union([zod.array(BreakdownApi).max(breakdownFilterApiBreakdownsOneMax), zod.null()]).optional(),
})

export type BreakdownFilterApi = zod.input<typeof BreakdownFilterApi>
export type BreakdownFilterApiOutput = zod.output<typeof BreakdownFilterApi>

export const IntervalTypeApi = zod.enum(['second', 'minute', 'hour', 'day', 'week', 'month', 'quarter', 'year'])

export type IntervalTypeApi = zod.input<typeof IntervalTypeApi>
export type IntervalTypeApiOutput = zod.output<typeof IntervalTypeApi>

export const PropertyOperatorApi = zod.enum([
    'exact',
    'is_not',
    'icontains',
    'not_icontains',
    'starts_with',
    'not_starts_with',
    'ends_with',
    'not_ends_with',
    'regex',
    'not_regex',
    'gt',
    'gte',
    'lt',
    'lte',
    'is_set',
    'is_not_set',
    'is_date_exact',
    'is_date_before',
    'is_date_after',
    'between',
    'not_between',
    'min',
    'max',
    'in',
    'not_in',
    'is_cleaned_path_exact',
    'flag_evaluates_to',
    'semver_eq',
    'semver_neq',
    'semver_gt',
    'semver_gte',
    'semver_lt',
    'semver_lte',
    'semver_tilde',
    'semver_caret',
    'semver_wildcard',
    'icontains_multi',
    'not_icontains_multi',
])

export type PropertyOperatorApi = zod.input<typeof PropertyOperatorApi>
export type PropertyOperatorApiOutput = zod.output<typeof PropertyOperatorApi>

export const eventPropertyFilterApiOperatorDefault = `exact`
export const eventPropertyFilterApiTypeDefault = `event`

export const EventPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: zod.union([PropertyOperatorApi, zod.null()]).default(eventPropertyFilterApiOperatorDefault),
    type: zod.literal('event').default(eventPropertyFilterApiTypeDefault).describe('Event properties'),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type EventPropertyFilterApi = zod.input<typeof EventPropertyFilterApi>
export type EventPropertyFilterApiOutput = zod.output<typeof EventPropertyFilterApi>

export const personPropertyFilterApiTypeDefault = `person`

export const PersonPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('person').default(personPropertyFilterApiTypeDefault).describe('Person properties'),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type PersonPropertyFilterApi = zod.input<typeof PersonPropertyFilterApi>
export type PersonPropertyFilterApiOutput = zod.output<typeof PersonPropertyFilterApi>

export const personMetadataPropertyFilterApiTypeDefault = `person_metadata`

export const PersonMetadataPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod
        .literal('person_metadata')
        .default(personMetadataPropertyFilterApiTypeDefault)
        .describe('Top-level columns on the persons table (e.g. created_at), not properties JSON'),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type PersonMetadataPropertyFilterApi = zod.input<typeof PersonMetadataPropertyFilterApi>
export type PersonMetadataPropertyFilterApiOutput = zod.output<typeof PersonMetadataPropertyFilterApi>

export const Key10Api = zod.enum(['tag_name', 'text', 'href', 'selector'])

export type Key10Api = zod.input<typeof Key10Api>
export type Key10ApiOutput = zod.output<typeof Key10Api>

export const elementPropertyFilterApiTypeDefault = `element`

export const ElementPropertyFilterApi = zod.object({
    key: Key10Api,
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('element').default(elementPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type ElementPropertyFilterApi = zod.input<typeof ElementPropertyFilterApi>
export type ElementPropertyFilterApiOutput = zod.output<typeof ElementPropertyFilterApi>

export const eventMetadataPropertyFilterApiTypeDefault = `event_metadata`

export const EventMetadataPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('event_metadata').default(eventMetadataPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type EventMetadataPropertyFilterApi = zod.input<typeof EventMetadataPropertyFilterApi>
export type EventMetadataPropertyFilterApiOutput = zod.output<typeof EventMetadataPropertyFilterApi>

export const sessionPropertyFilterApiTypeDefault = `session`

export const SessionPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('session').default(sessionPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type SessionPropertyFilterApi = zod.input<typeof SessionPropertyFilterApi>
export type SessionPropertyFilterApiOutput = zod.output<typeof SessionPropertyFilterApi>

export const cohortPropertyFilterApiKeyDefault = `id`
export const cohortPropertyFilterApiOperatorDefault = `in`
export const cohortPropertyFilterApiTypeDefault = `cohort`

export const CohortPropertyFilterApi = zod.object({
    cohort_name: zod.union([zod.string(), zod.null()]).optional(),
    key: zod.literal('id').default(cohortPropertyFilterApiKeyDefault),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: zod.union([PropertyOperatorApi, zod.null()]).default(cohortPropertyFilterApiOperatorDefault),
    type: zod.literal('cohort').default(cohortPropertyFilterApiTypeDefault),
    value: zod.number(),
})

export type CohortPropertyFilterApi = zod.input<typeof CohortPropertyFilterApi>
export type CohortPropertyFilterApiOutput = zod.output<typeof CohortPropertyFilterApi>

export const DurationTypeApi = zod.enum(['duration', 'active_seconds', 'inactive_seconds'])

export type DurationTypeApi = zod.input<typeof DurationTypeApi>
export type DurationTypeApiOutput = zod.output<typeof DurationTypeApi>

export const recordingPropertyFilterApiTypeDefault = `recording`

export const RecordingPropertyFilterApi = zod.object({
    key: zod.union([DurationTypeApi, zod.string()]),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('recording').default(recordingPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type RecordingPropertyFilterApi = zod.input<typeof RecordingPropertyFilterApi>
export type RecordingPropertyFilterApiOutput = zod.output<typeof RecordingPropertyFilterApi>

export const logEntryPropertyFilterApiTypeDefault = `log_entry`

export const LogEntryPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('log_entry').default(logEntryPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type LogEntryPropertyFilterApi = zod.input<typeof LogEntryPropertyFilterApi>
export type LogEntryPropertyFilterApiOutput = zod.output<typeof LogEntryPropertyFilterApi>

export const groupPropertyFilterApiTypeDefault = `group`

export const GroupPropertyFilterApi = zod.object({
    group_key_names: zod.union([zod.record(zod.string(), zod.string()), zod.null()]).optional(),
    group_type_index: zod.union([zod.number(), zod.null()]).optional(),
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('group').default(groupPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type GroupPropertyFilterApi = zod.input<typeof GroupPropertyFilterApi>
export type GroupPropertyFilterApiOutput = zod.output<typeof GroupPropertyFilterApi>

export const featurePropertyFilterApiTypeDefault = `feature`

export const FeaturePropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod
        .literal('feature')
        .default(featurePropertyFilterApiTypeDefault)
        .describe('Event property with \"$feature\/\" prepended'),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type FeaturePropertyFilterApi = zod.input<typeof FeaturePropertyFilterApi>
export type FeaturePropertyFilterApiOutput = zod.output<typeof FeaturePropertyFilterApi>

export const flagPropertyFilterApiOperatorDefault = `flag_evaluates_to`
export const flagPropertyFilterApiTypeDefault = `flag`

export const FlagPropertyFilterApi = zod.object({
    key: zod.string().describe('The key should be the flag ID'),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: zod
        .literal('flag_evaluates_to')
        .default(flagPropertyFilterApiOperatorDefault)
        .describe('Only flag_evaluates_to operator is allowed for flag dependencies'),
    type: zod.literal('flag').default(flagPropertyFilterApiTypeDefault).describe('Feature flag dependency'),
    value: zod.union([zod.boolean(), zod.string()]).describe('The value can be true, false, or a variant name'),
})

export type FlagPropertyFilterApi = zod.input<typeof FlagPropertyFilterApi>
export type FlagPropertyFilterApiOutput = zod.output<typeof FlagPropertyFilterApi>

export const hogQLPropertyFilterApiTypeDefault = `hogql`

export const HogQLPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    type: zod.literal('hogql').default(hogQLPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type HogQLPropertyFilterApi = zod.input<typeof HogQLPropertyFilterApi>
export type HogQLPropertyFilterApiOutput = zod.output<typeof HogQLPropertyFilterApi>

export const emptyPropertyFilterApiTypeDefault = `empty`

export const EmptyPropertyFilterApi = zod.object({
    type: zod.literal('empty').default(emptyPropertyFilterApiTypeDefault),
})

export type EmptyPropertyFilterApi = zod.input<typeof EmptyPropertyFilterApi>
export type EmptyPropertyFilterApiOutput = zod.output<typeof EmptyPropertyFilterApi>

export const dataWarehousePropertyFilterApiTypeDefault = `data_warehouse`

export const DataWarehousePropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('data_warehouse').default(dataWarehousePropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type DataWarehousePropertyFilterApi = zod.input<typeof DataWarehousePropertyFilterApi>
export type DataWarehousePropertyFilterApiOutput = zod.output<typeof DataWarehousePropertyFilterApi>

export const dataWarehousePersonPropertyFilterApiTypeDefault = `data_warehouse_person_property`

export const DataWarehousePersonPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('data_warehouse_person_property').default(dataWarehousePersonPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type DataWarehousePersonPropertyFilterApi = zod.input<typeof DataWarehousePersonPropertyFilterApi>
export type DataWarehousePersonPropertyFilterApiOutput = zod.output<typeof DataWarehousePersonPropertyFilterApi>

export const errorTrackingIssueFilterApiTypeDefault = `error_tracking_issue`

export const ErrorTrackingIssueFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('error_tracking_issue').default(errorTrackingIssueFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type ErrorTrackingIssueFilterApi = zod.input<typeof ErrorTrackingIssueFilterApi>
export type ErrorTrackingIssueFilterApiOutput = zod.output<typeof ErrorTrackingIssueFilterApi>

export const LogPropertyFilterTypeApi = zod.enum(['log', 'log_attribute', 'log_resource_attribute'])

export type LogPropertyFilterTypeApi = zod.input<typeof LogPropertyFilterTypeApi>
export type LogPropertyFilterTypeApiOutput = zod.output<typeof LogPropertyFilterTypeApi>

export const LogPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: LogPropertyFilterTypeApi,
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type LogPropertyFilterApi = zod.input<typeof LogPropertyFilterApi>
export type LogPropertyFilterApiOutput = zod.output<typeof LogPropertyFilterApi>

export const metricPropertyFilterApiTypeDefault = `metric_attribute`

export const MetricPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('metric_attribute').default(metricPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type MetricPropertyFilterApi = zod.input<typeof MetricPropertyFilterApi>
export type MetricPropertyFilterApiOutput = zod.output<typeof MetricPropertyFilterApi>

export const SpanPropertyFilterTypeApi = zod.enum(['span', 'span_attribute', 'span_resource_attribute'])

export type SpanPropertyFilterTypeApi = zod.input<typeof SpanPropertyFilterTypeApi>
export type SpanPropertyFilterTypeApiOutput = zod.output<typeof SpanPropertyFilterTypeApi>

export const SpanPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: SpanPropertyFilterTypeApi,
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type SpanPropertyFilterApi = zod.input<typeof SpanPropertyFilterApi>
export type SpanPropertyFilterApiOutput = zod.output<typeof SpanPropertyFilterApi>

export const revenueAnalyticsPropertyFilterApiTypeDefault = `revenue_analytics`

export const RevenueAnalyticsPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('revenue_analytics').default(revenueAnalyticsPropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type RevenueAnalyticsPropertyFilterApi = zod.input<typeof RevenueAnalyticsPropertyFilterApi>
export type RevenueAnalyticsPropertyFilterApiOutput = zod.output<typeof RevenueAnalyticsPropertyFilterApi>

export const accountCustomPropertyFilterApiTypeDefault = `account_custom_property`

export const AccountCustomPropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod
        .literal('account_custom_property')
        .default(accountCustomPropertyFilterApiTypeDefault)
        .describe('Customer analytics account custom property — the key is the property definition id'),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type AccountCustomPropertyFilterApi = zod.input<typeof AccountCustomPropertyFilterApi>
export type AccountCustomPropertyFilterApiOutput = zod.output<typeof AccountCustomPropertyFilterApi>

export const workflowVariablePropertyFilterApiTypeDefault = `workflow_variable`

export const WorkflowVariablePropertyFilterApi = zod.object({
    key: zod.string(),
    label: zod.union([zod.string(), zod.null()]).optional(),
    operator: PropertyOperatorApi,
    type: zod.literal('workflow_variable').default(workflowVariablePropertyFilterApiTypeDefault),
    value: zod
        .union([
            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
            zod.string(),
            zod.number(),
            zod.boolean(),
            zod.null(),
        ])
        .optional(),
})

export type WorkflowVariablePropertyFilterApi = zod.input<typeof WorkflowVariablePropertyFilterApi>
export type WorkflowVariablePropertyFilterApiOutput = zod.output<typeof WorkflowVariablePropertyFilterApi>
