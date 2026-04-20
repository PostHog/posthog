// AUTO-GENERATED from products/error_tracking/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    ErrorTrackingAssignmentRulesCreateBody,
    ErrorTrackingAssignmentRulesListQueryParams,
    ErrorTrackingGroupingRulesCreateBody,
    ErrorTrackingIssuesListQueryParams,
    ErrorTrackingIssuesMergeCreateBody,
    ErrorTrackingIssuesMergeCreateParams,
    ErrorTrackingIssuesPartialUpdateBody,
    ErrorTrackingIssuesPartialUpdateParams,
    ErrorTrackingIssuesRetrieveParams,
    ErrorTrackingIssuesSplitCreateBody,
    ErrorTrackingIssuesSplitCreateParams,
    ErrorTrackingSuppressionRulesListQueryParams,
} from '@/generated/error_tracking/api'
import { withUiApp } from '@/resources/ui-apps'
import { createQueryWrapper } from '@/tools/query-wrapper-factory'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ErrorTrackingAssignmentRulesListSchema = ErrorTrackingAssignmentRulesListQueryParams

const errorTrackingAssignmentRulesList = (): ToolBase<
    typeof ErrorTrackingAssignmentRulesListSchema,
    Schemas.PaginatedErrorTrackingAssignmentRuleList
> => ({
    name: 'error-tracking-assignment-rules-list',
    schema: ErrorTrackingAssignmentRulesListSchema,
    handler: async (context: Context, params: z.infer<typeof ErrorTrackingAssignmentRulesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedErrorTrackingAssignmentRuleList>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/error_tracking/assignment_rules/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

const ErrorTrackingAssignmentRulesCreateSchema = ErrorTrackingAssignmentRulesCreateBody

const errorTrackingAssignmentRulesCreate = (): ToolBase<
    typeof ErrorTrackingAssignmentRulesCreateSchema,
    Schemas.ErrorTrackingAssignmentRule
> => ({
    name: 'error-tracking-assignment-rules-create',
    schema: ErrorTrackingAssignmentRulesCreateSchema,
    handler: async (context: Context, params: z.infer<typeof ErrorTrackingAssignmentRulesCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.assignee !== undefined) {
            body['assignee'] = params.assignee
        }
        const result = await context.api.request<Schemas.ErrorTrackingAssignmentRule>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/error_tracking/assignment_rules/`,
            body,
        })
        return result
    },
})

const ErrorTrackingGroupingRulesListSchema = z.object({})

const errorTrackingGroupingRulesList = (): ToolBase<
    typeof ErrorTrackingGroupingRulesListSchema,
    Schemas.ErrorTrackingGroupingRuleListResponse
> => ({
    name: 'error-tracking-grouping-rules-list',
    schema: ErrorTrackingGroupingRulesListSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof ErrorTrackingGroupingRulesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ErrorTrackingGroupingRuleListResponse>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/error_tracking/grouping_rules/`,
        })
        return result
    },
})

const ErrorTrackingGroupingRulesCreateSchema = ErrorTrackingGroupingRulesCreateBody

const errorTrackingGroupingRulesCreate = (): ToolBase<
    typeof ErrorTrackingGroupingRulesCreateSchema,
    Schemas.ErrorTrackingGroupingRule
> => ({
    name: 'error-tracking-grouping-rules-create',
    schema: ErrorTrackingGroupingRulesCreateSchema,
    handler: async (context: Context, params: z.infer<typeof ErrorTrackingGroupingRulesCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.assignee !== undefined) {
            body['assignee'] = params.assignee
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        const result = await context.api.request<Schemas.ErrorTrackingGroupingRule>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/error_tracking/grouping_rules/`,
            body,
        })
        return result
    },
})

const ErrorTrackingIssuesListSchema = ErrorTrackingIssuesListQueryParams

const errorTrackingIssuesList = (): ToolBase<
    typeof ErrorTrackingIssuesListSchema,
    WithPostHogUrl<Schemas.PaginatedErrorTrackingIssueFullList>
> =>
    withUiApp('error-issue-list', {
        name: 'error-tracking-issues-list',
        schema: ErrorTrackingIssuesListSchema,
        handler: async (context: Context, params: z.infer<typeof ErrorTrackingIssuesListSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.PaginatedErrorTrackingIssueFullList>({
                method: 'GET',
                path: `/api/environments/${encodeURIComponent(String(projectId))}/error_tracking/issues/`,
                query: {
                    limit: params.limit,
                    offset: params.offset,
                },
            })
            const filtered = {
                ...result,
                results: (result.results ?? []).map((item: any) =>
                    pickResponseFields(item, ['id', 'status', 'name', 'first_seen', 'assignee'])
                ),
            } as typeof result
            return await withPostHogUrl(
                context,
                {
                    ...filtered,
                    results: await Promise.all(
                        (filtered.results ?? []).map((item) =>
                            withPostHogUrl(context, item, `/error_tracking/${item.id}`)
                        )
                    ),
                },
                '/error_tracking'
            )
        },
    })

const ErrorTrackingIssuesRetrieveSchema = ErrorTrackingIssuesRetrieveParams.omit({ project_id: true })

const errorTrackingIssuesRetrieve = (): ToolBase<
    typeof ErrorTrackingIssuesRetrieveSchema,
    WithPostHogUrl<Schemas.ErrorTrackingIssueFull>
> =>
    withUiApp('error-issue', {
        name: 'error-tracking-issues-retrieve',
        schema: ErrorTrackingIssuesRetrieveSchema,
        handler: async (context: Context, params: z.infer<typeof ErrorTrackingIssuesRetrieveSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.ErrorTrackingIssueFull>({
                method: 'GET',
                path: `/api/environments/${encodeURIComponent(String(projectId))}/error_tracking/issues/${encodeURIComponent(String(params.id))}/`,
            })
            return await withPostHogUrl(context, result, `/error_tracking/${result.id}`)
        },
    })

const ErrorTrackingIssuesPartialUpdateSchema = ErrorTrackingIssuesPartialUpdateParams.omit({ project_id: true }).extend(
    ErrorTrackingIssuesPartialUpdateBody.shape
)

const errorTrackingIssuesPartialUpdate = (): ToolBase<
    typeof ErrorTrackingIssuesPartialUpdateSchema,
    WithPostHogUrl<Schemas.ErrorTrackingIssueFull>
> =>
    withUiApp('error-issue', {
        name: 'error-tracking-issues-partial-update',
        schema: ErrorTrackingIssuesPartialUpdateSchema,
        handler: async (context: Context, params: z.infer<typeof ErrorTrackingIssuesPartialUpdateSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const body: Record<string, unknown> = {}
            if (params.status !== undefined) {
                body['status'] = params.status
            }
            if (params.name !== undefined) {
                body['name'] = params.name
            }
            if (params.description !== undefined) {
                body['description'] = params.description
            }
            if (params.first_seen !== undefined) {
                body['first_seen'] = params.first_seen
            }
            if (params.assignee !== undefined) {
                body['assignee'] = params.assignee
            }
            if (params.external_issues !== undefined) {
                body['external_issues'] = params.external_issues
            }
            const result = await context.api.request<Schemas.ErrorTrackingIssueFull>({
                method: 'PATCH',
                path: `/api/environments/${encodeURIComponent(String(projectId))}/error_tracking/issues/${encodeURIComponent(String(params.id))}/`,
                body,
            })
            return await withPostHogUrl(context, result, `/error_tracking/${result.id}`)
        },
    })

const ErrorTrackingIssuesMergeCreateSchema = ErrorTrackingIssuesMergeCreateParams.omit({ project_id: true }).extend(
    ErrorTrackingIssuesMergeCreateBody.shape
)

const errorTrackingIssuesMergeCreate = (): ToolBase<
    typeof ErrorTrackingIssuesMergeCreateSchema,
    Schemas.ErrorTrackingIssueMergeResponse
> => ({
    name: 'error-tracking-issues-merge-create',
    schema: ErrorTrackingIssuesMergeCreateSchema,
    handler: async (context: Context, params: z.infer<typeof ErrorTrackingIssuesMergeCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.ids !== undefined) {
            body['ids'] = params.ids
        }
        const result = await context.api.request<Schemas.ErrorTrackingIssueMergeResponse>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/error_tracking/issues/${encodeURIComponent(String(params.id))}/merge/`,
            body,
        })
        return result
    },
})

const ErrorTrackingIssuesSplitCreateSchema = ErrorTrackingIssuesSplitCreateParams.omit({ project_id: true }).extend(
    ErrorTrackingIssuesSplitCreateBody.shape
)

const errorTrackingIssuesSplitCreate = (): ToolBase<
    typeof ErrorTrackingIssuesSplitCreateSchema,
    Schemas.ErrorTrackingIssueSplitResponse
> => ({
    name: 'error-tracking-issues-split-create',
    schema: ErrorTrackingIssuesSplitCreateSchema,
    handler: async (context: Context, params: z.infer<typeof ErrorTrackingIssuesSplitCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.fingerprints !== undefined) {
            body['fingerprints'] = params.fingerprints
        }
        const result = await context.api.request<Schemas.ErrorTrackingIssueSplitResponse>({
            method: 'POST',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/error_tracking/issues/${encodeURIComponent(String(params.id))}/split/`,
            body,
        })
        return result
    },
})

const ErrorTrackingSuppressionRulesListSchema = ErrorTrackingSuppressionRulesListQueryParams

const errorTrackingSuppressionRulesList = (): ToolBase<
    typeof ErrorTrackingSuppressionRulesListSchema,
    Schemas.PaginatedErrorTrackingSuppressionRuleList
> => ({
    name: 'error-tracking-suppression-rules-list',
    schema: ErrorTrackingSuppressionRulesListSchema,
    handler: async (context: Context, params: z.infer<typeof ErrorTrackingSuppressionRulesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedErrorTrackingSuppressionRuleList>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/error_tracking/suppression_rules/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

// --- Query wrapper schemas from schema.json ---

const integer = z.coerce.number().int()

const ErrorTrackingIssueAssigneeType = z.enum(['user', 'role'])

const ErrorTrackingIssueAssignee = z.object({
    id: z.union([integer, z.string()]),
    type: ErrorTrackingIssueAssigneeType,
})

const DateRange = z.object({
    date_from: z
        .string()
        .nullable()
        .describe(
            'Start of the date range. Accepts ISO 8601 timestamps (e.g., 2024-01-15T00:00:00Z) or relative formats: -7d (7 days ago), -2w (2 weeks ago), -1m (1 month ago),\n-1h (1 hour ago), -1mStart (start of last month), -1yStart (start of last year).'
        )
        .optional(),
    date_to: z
        .string()
        .nullable()
        .describe('End of the date range. Same format as date_from. Omit or null for "now".')
        .optional(),
    explicitDate: z.coerce
        .boolean()
        .nullable()
        .describe(
            'Whether the date_from and date_to should be used verbatim. Disables rounding to the start and end of period.'
        )
        .default(false)
        .optional(),
})

const AssistantStringOrBooleanValuePropertyFilterOperator = z.enum([
    'exact',
    'is_not',
    'icontains',
    'not_icontains',
    'regex',
    'not_regex',
])

const AssistantGenericPropertyFilterType = z.enum(['event', 'person', 'session', 'feature'])

const AssistantNumericValuePropertyFilterOperator = z.enum(['exact', 'gt', 'lt'])

const AssistantArrayPropertyFilterOperator = z.enum(['exact', 'is_not'])

const AssistantDateTimePropertyFilterOperator = z.enum(['is_date_exact', 'is_date_before', 'is_date_after'])

const AssistantSetPropertyFilterOperator = z.enum(['is_set', 'is_not_set'])

const AssistantGenericPropertyFilter = z.union([
    z.object({
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantStringOrBooleanValuePropertyFilterOperator.describe(
            '`icontains` - case insensitive contains. `not_icontains` - case insensitive does not contain. `regex` - matches the regex pattern. `not_regex` - does not match the regex pattern.'
        ),
        type: AssistantGenericPropertyFilterType,
        value: z
            .string()
            .describe(
                'Only use property values from the plan. If the operator is `regex` or `not_regex`, the value must be a valid ClickHouse regex pattern to match against. Otherwise, the value must be a substring that will be matched against the property value. Use the string values `true` or `false` for boolean properties.'
            ),
    }),
    z.object({
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantNumericValuePropertyFilterOperator,
        type: AssistantGenericPropertyFilterType,
        value: z.coerce.number(),
    }),
    z.object({
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantArrayPropertyFilterOperator.describe(
            '`exact` - exact match of any of the values. `is_not` - does not match any of the values.'
        ),
        type: AssistantGenericPropertyFilterType,
        value: z
            .array(z.string())
            .describe(
                'Only use property values from the plan. Always use strings as values. If you have a number, convert it to a string first. If you have a boolean, convert it to a string "true" or "false".'
            ),
    }),
    z.object({
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantDateTimePropertyFilterOperator,
        type: AssistantGenericPropertyFilterType,
        value: z.string().describe('Value must be a date in ISO 8601 format.'),
    }),
    z.object({
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantSetPropertyFilterOperator.describe(
            "`is_set` - the property has any value. `is_not_set` - the property doesn't have a value or wasn't collected."
        ),
        type: AssistantGenericPropertyFilterType,
    }),
])

const AssistantGroupPropertyFilter = z.union([
    z.object({
        group_type_index: integer.describe('Index of the group type from the group mapping.'),
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantStringOrBooleanValuePropertyFilterOperator.describe(
            '`icontains` - case insensitive contains. `not_icontains` - case insensitive does not contain. `regex` - matches the regex pattern. `not_regex` - does not match the regex pattern.'
        ),
        type: z.literal('group').default('group'),
        value: z
            .string()
            .describe(
                'Only use property values from the plan. If the operator is `regex` or `not_regex`, the value must be a valid ClickHouse regex pattern to match against. Otherwise, the value must be a substring that will be matched against the property value. Use the string values `true` or `false` for boolean properties.'
            ),
    }),
    z.object({
        group_type_index: integer.describe('Index of the group type from the group mapping.'),
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantNumericValuePropertyFilterOperator,
        type: z.literal('group').default('group'),
        value: z.coerce.number(),
    }),
    z.object({
        group_type_index: integer.describe('Index of the group type from the group mapping.'),
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantArrayPropertyFilterOperator.describe(
            '`exact` - exact match of any of the values. `is_not` - does not match any of the values.'
        ),
        type: z.literal('group').default('group'),
        value: z
            .array(z.string())
            .describe(
                'Only use property values from the plan. Always use strings as values. If you have a number, convert it to a string first. If you have a boolean, convert it to a string "true" or "false".'
            ),
    }),
    z.object({
        group_type_index: integer.describe('Index of the group type from the group mapping.'),
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantDateTimePropertyFilterOperator,
        type: z.literal('group').default('group'),
        value: z.string().describe('Value must be a date in ISO 8601 format.'),
    }),
    z.object({
        group_type_index: integer.describe('Index of the group type from the group mapping.'),
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantSetPropertyFilterOperator.describe(
            "`is_set` - the property has any value. `is_not_set` - the property doesn't have a value or wasn't collected."
        ),
        type: z.literal('group').default('group'),
    }),
])

const AssistantCohortPropertyFilter = z.object({
    key: z.literal('id').default('id'),
    operator: z.literal('in').default('in'),
    type: z
        .literal('cohort')
        .describe(
            'Filter events by cohort membership. Use this to narrow down results to persons belonging to a specific cohort. Example: `{ type: "cohort", key: "id", value: 42, operator: "in" }`'
        )
        .default('cohort'),
    value: integer.describe('The cohort ID to filter by.'),
})

const AssistantElementPropertyFilter = z.union([
    z.object({
        key: z
            .enum(['tag_name', 'text', 'href', 'selector'])
            .describe(
                'The element property to filter on. `tag_name` — HTML tag (e.g., `button`, `a`, `input`). `text` — visible text content of the element. `href` — the `href` attribute for links. `selector` — a CSS selector matching the element (e.g., `div.main > button.cta`).'
            ),
        operator: AssistantStringOrBooleanValuePropertyFilterOperator.describe(
            '`icontains` - case insensitive contains. `not_icontains` - case insensitive does not contain. `regex` - matches the regex pattern. `not_regex` - does not match the regex pattern.'
        ),
        type: z
            .literal('element')
            .describe(
                'Filter by autocaptured HTML element properties (`$autocapture`, `$rageclick`). Example: `{ type: "element", key: "text", value: "Sign Up", operator: "exact" }`'
            )
            .default('element'),
        value: z
            .string()
            .describe(
                'Only use property values from the plan. If the operator is `regex` or `not_regex`, the value must be a valid ClickHouse regex pattern to match against. Otherwise, the value must be a substring that will be matched against the property value. Use the string values `true` or `false` for boolean properties.'
            ),
    }),
    z.object({
        key: z
            .enum(['tag_name', 'text', 'href', 'selector'])
            .describe(
                'The element property to filter on. `tag_name` — HTML tag (e.g., `button`, `a`, `input`). `text` — visible text content of the element. `href` — the `href` attribute for links. `selector` — a CSS selector matching the element (e.g., `div.main > button.cta`).'
            ),
        operator: AssistantNumericValuePropertyFilterOperator,
        type: z
            .literal('element')
            .describe(
                'Filter by autocaptured HTML element properties (`$autocapture`, `$rageclick`). Example: `{ type: "element", key: "text", value: "Sign Up", operator: "exact" }`'
            )
            .default('element'),
        value: z.coerce.number(),
    }),
    z.object({
        key: z
            .enum(['tag_name', 'text', 'href', 'selector'])
            .describe(
                'The element property to filter on. `tag_name` — HTML tag (e.g., `button`, `a`, `input`). `text` — visible text content of the element. `href` — the `href` attribute for links. `selector` — a CSS selector matching the element (e.g., `div.main > button.cta`).'
            ),
        operator: AssistantArrayPropertyFilterOperator.describe(
            '`exact` - exact match of any of the values. `is_not` - does not match any of the values.'
        ),
        type: z
            .literal('element')
            .describe(
                'Filter by autocaptured HTML element properties (`$autocapture`, `$rageclick`). Example: `{ type: "element", key: "text", value: "Sign Up", operator: "exact" }`'
            )
            .default('element'),
        value: z
            .array(z.string())
            .describe(
                'Only use property values from the plan. Always use strings as values. If you have a number, convert it to a string first. If you have a boolean, convert it to a string "true" or "false".'
            ),
    }),
    z.object({
        key: z
            .enum(['tag_name', 'text', 'href', 'selector'])
            .describe(
                'The element property to filter on. `tag_name` — HTML tag (e.g., `button`, `a`, `input`). `text` — visible text content of the element. `href` — the `href` attribute for links. `selector` — a CSS selector matching the element (e.g., `div.main > button.cta`).'
            ),
        operator: AssistantDateTimePropertyFilterOperator,
        type: z
            .literal('element')
            .describe(
                'Filter by autocaptured HTML element properties (`$autocapture`, `$rageclick`). Example: `{ type: "element", key: "text", value: "Sign Up", operator: "exact" }`'
            )
            .default('element'),
        value: z.string().describe('Value must be a date in ISO 8601 format.'),
    }),
    z.object({
        key: z
            .enum(['tag_name', 'text', 'href', 'selector'])
            .describe(
                'The element property to filter on. `tag_name` — HTML tag (e.g., `button`, `a`, `input`). `text` — visible text content of the element. `href` — the `href` attribute for links. `selector` — a CSS selector matching the element (e.g., `div.main > button.cta`).'
            ),
        operator: AssistantSetPropertyFilterOperator.describe(
            "`is_set` - the property has any value. `is_not_set` - the property doesn't have a value or wasn't collected."
        ),
        type: z
            .literal('element')
            .describe(
                'Filter by autocaptured HTML element properties (`$autocapture`, `$rageclick`). Example: `{ type: "element", key: "text", value: "Sign Up", operator: "exact" }`'
            )
            .default('element'),
    }),
])

const AssistantHogQLPropertyFilter = z.object({
    key: z
        .string()
        .describe(
            "A HogQL boolean expression used as a filter condition.\n\nExamples:\n- Filter where a property exceeds a threshold: `toFloat(properties.load_time) > 5.0`\n- Filter with string matching: `properties.$current_url LIKE '%/pricing%'`\n- Filter with multiple conditions: `properties.$browser = 'Chrome' AND toFloat(properties.duration) > 30`"
        ),
    type: z
        .literal('hogql')
        .describe(
            "Filter by a HogQL boolean expression for advanced filtering that can't be expressed with standard property filters."
        )
        .default('hogql'),
})

const AssistantFlagPropertyFilter = z.object({
    key: z.string().describe('The feature flag key.'),
    operator: z.literal('flag_evaluates_to').default('flag_evaluates_to'),
    type: z
        .literal('flag')
        .describe(
            'Filter events by feature flag state — only include events where a specific flag evaluated to a given value. Examples:\n- Flag enabled: `{ type: "flag", key: "new-onboarding", operator: "flag_evaluates_to", value: true }`\n- Specific variant: `{ type: "flag", key: "checkout-experiment", operator: "flag_evaluates_to", value: "variant-a" }`'
        )
        .default('flag'),
    value: z
        .union([z.coerce.boolean(), z.string()])
        .describe('`true`/`false` for boolean flags, or a variant name string for multivariate flags.'),
})

const AssistantPropertyFilter = z.union([
    AssistantGenericPropertyFilter,
    AssistantGroupPropertyFilter,
    AssistantCohortPropertyFilter,
    AssistantElementPropertyFilter,
    AssistantHogQLPropertyFilter,
    AssistantFlagPropertyFilter,
])

const ErrorTrackingOrderBy = z.enum(['last_seen', 'first_seen', 'occurrences', 'users', 'sessions'])

const ErrorTrackingIssueStatus = z.enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])

const ErrorTrackingQueryStatus = z.union([ErrorTrackingIssueStatus, z.literal('all')])

const AssistantErrorTrackingQuery = z.object({
    assignee: z.union([ErrorTrackingIssueAssignee, z.null()]).describe('Filter by assignee.').optional(),
    dateRange: DateRange.describe('Date range to filter results.').optional(),
    filterGroup: z.array(AssistantPropertyFilter).describe('Property filters for the query').default([]).optional(),
    filterTestAccounts: z.coerce.boolean().describe('Whether to filter out test accounts.').optional(),
    issueId: z.string().describe('Filter to a specific error tracking issue by ID.').optional(),
    kind: z.literal('ErrorTrackingQuery').default('ErrorTrackingQuery'),
    limit: integer.optional(),
    offset: integer.optional(),
    orderBy: ErrorTrackingOrderBy.describe('Field to sort results by.').optional(),
    orderDirection: z.enum(['ASC', 'DESC']).describe('Sort direction.').optional(),
    searchQuery: z.string().describe('Free-text search across exception type, message, and stack frames.').optional(),
    status: ErrorTrackingQueryStatus.describe('Filter by issue status.').optional(),
    volumeResolution: integer
        .describe('Controls volume chart granularity. Use 1 for sparklines, 0 for counts only.')
        .optional(),
})

const QueryErrorTrackingIssuesSchema = AssistantErrorTrackingQuery.extend({
    limit: AssistantErrorTrackingQuery.shape.limit.default(50).optional(),
    orderBy: AssistantErrorTrackingQuery.shape.orderBy.default('occurrences').optional(),
    volumeResolution: AssistantErrorTrackingQuery.shape.volumeResolution.default(1).optional(),
    dateRange: AssistantErrorTrackingQuery.shape.dateRange.default({ date_from: '-7d' }).optional(),
    filterTestAccounts: AssistantErrorTrackingQuery.shape.filterTestAccounts.default(true).optional(),
    status: AssistantErrorTrackingQuery.shape.status.default('active').optional(),
    orderDirection: AssistantErrorTrackingQuery.shape.orderDirection.default('DESC').optional(),
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'error-tracking-assignment-rules-list': errorTrackingAssignmentRulesList,
    'error-tracking-assignment-rules-create': errorTrackingAssignmentRulesCreate,
    'error-tracking-grouping-rules-list': errorTrackingGroupingRulesList,
    'error-tracking-grouping-rules-create': errorTrackingGroupingRulesCreate,
    'error-tracking-issues-list': errorTrackingIssuesList,
    'error-tracking-issues-retrieve': errorTrackingIssuesRetrieve,
    'error-tracking-issues-partial-update': errorTrackingIssuesPartialUpdate,
    'error-tracking-issues-merge-create': errorTrackingIssuesMergeCreate,
    'error-tracking-issues-split-create': errorTrackingIssuesSplitCreate,
    'error-tracking-suppression-rules-list': errorTrackingSuppressionRulesList,
    'query-error-tracking-issues': createQueryWrapper({
        name: 'query-error-tracking-issues',
        schema: QueryErrorTrackingIssuesSchema,
        kind: 'ErrorTrackingQuery',
        uiResourceUri: 'ui://posthog/error-issue-list.html',
        urlPrefix: '/error_tracking',
    }),
}
