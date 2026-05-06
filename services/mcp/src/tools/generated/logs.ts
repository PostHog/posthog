// AUTO-GENERATED from products/logs/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    LogsAlertsCreateBody,
    LogsAlertsDestinationsCreateBody,
    LogsAlertsDestinationsCreateParams,
    LogsAlertsDestinationsDeleteCreateBody,
    LogsAlertsDestinationsDeleteCreateParams,
    LogsAlertsDestroyParams,
    LogsAlertsEventsListParams,
    LogsAlertsEventsListQueryParams,
    LogsAlertsListQueryParams,
    LogsAlertsPartialUpdateBody,
    LogsAlertsPartialUpdateParams,
    LogsAlertsRetrieveParams,
    LogsAlertsSimulateCreateBody,
    LogsAttributesRetrieveQueryParams,
    LogsCountCreateBody,
    LogsCountRangesCreateBody,
    LogsQueryCreateBody,
    LogsServicesCreateBody,
    LogsSparklineCreateBody,
    LogsValuesRetrieveQueryParams,
} from '@/generated/logs/api'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const LogsAlertsCreateSchema = LogsAlertsCreateBody

const logsAlertsCreate = (): ToolBase<typeof LogsAlertsCreateSchema, Schemas.LogsAlertConfiguration> => ({
    name: 'logs-alerts-create',
    schema: LogsAlertsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LogsAlertsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.threshold_count !== undefined) {
            body['threshold_count'] = params.threshold_count
        }
        if (params.threshold_operator !== undefined) {
            body['threshold_operator'] = params.threshold_operator
        }
        if (params.window_minutes !== undefined) {
            body['window_minutes'] = params.window_minutes
        }
        if (params.evaluation_periods !== undefined) {
            body['evaluation_periods'] = params.evaluation_periods
        }
        if (params.datapoints_to_alarm !== undefined) {
            body['datapoints_to_alarm'] = params.datapoints_to_alarm
        }
        if (params.cooldown_minutes !== undefined) {
            body['cooldown_minutes'] = params.cooldown_minutes
        }
        if (params.snooze_until !== undefined) {
            body['snooze_until'] = params.snooze_until
        }
        const result = await context.api.request<Schemas.LogsAlertConfiguration>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/logs/alerts/`,
            body,
        })
        const filtered = pickResponseFields(result, [
            'id',
            'name',
            'enabled',
            'state',
            'filters',
            'threshold_count',
            'threshold_operator',
            'window_minutes',
            'check_interval_minutes',
            'evaluation_periods',
            'datapoints_to_alarm',
            'cooldown_minutes',
            'snooze_until',
            'next_check_at',
            'last_notified_at',
            'last_checked_at',
            'consecutive_failures',
            'last_error_message',
            'created_at',
            'updated_at',
        ]) as typeof result
        return filtered
    },
})

const LogsAlertsDestinationsCreateSchema = LogsAlertsDestinationsCreateParams.omit({ project_id: true }).extend(
    LogsAlertsDestinationsCreateBody.shape
)

const logsAlertsDestinationsCreate = (): ToolBase<
    typeof LogsAlertsDestinationsCreateSchema,
    Schemas.LogsAlertDestinationResponse
> => ({
    name: 'logs-alerts-destinations-create',
    schema: LogsAlertsDestinationsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LogsAlertsDestinationsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.type !== undefined) {
            body['type'] = params.type
        }
        if (params.slack_workspace_id !== undefined) {
            body['slack_workspace_id'] = params.slack_workspace_id
        }
        if (params.slack_channel_id !== undefined) {
            body['slack_channel_id'] = params.slack_channel_id
        }
        if (params.slack_channel_name !== undefined) {
            body['slack_channel_name'] = params.slack_channel_name
        }
        if (params.webhook_url !== undefined) {
            body['webhook_url'] = params.webhook_url
        }
        const result = await context.api.request<Schemas.LogsAlertDestinationResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/logs/alerts/${encodeURIComponent(String(params.id))}/destinations/`,
            body,
        })
        const filtered = pickResponseFields(result, ['hog_function_ids']) as typeof result
        return filtered
    },
})

const LogsAlertsDestinationsDeleteCreateSchema = LogsAlertsDestinationsDeleteCreateParams.omit({
    project_id: true,
}).extend(LogsAlertsDestinationsDeleteCreateBody.shape)

const logsAlertsDestinationsDeleteCreate = (): ToolBase<typeof LogsAlertsDestinationsDeleteCreateSchema, unknown> => ({
    name: 'logs-alerts-destinations-delete-create',
    schema: LogsAlertsDestinationsDeleteCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LogsAlertsDestinationsDeleteCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.hog_function_ids !== undefined) {
            body['hog_function_ids'] = params.hog_function_ids
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/logs/alerts/${encodeURIComponent(String(params.id))}/destinations/delete/`,
            body,
        })
        return result
    },
})

const LogsAlertsDestroySchema = LogsAlertsDestroyParams.omit({ project_id: true })

const logsAlertsDestroy = (): ToolBase<typeof LogsAlertsDestroySchema, unknown> => ({
    name: 'logs-alerts-destroy',
    schema: LogsAlertsDestroySchema,
    handler: async (context: Context, params: z.infer<typeof LogsAlertsDestroySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/logs/alerts/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const LogsAlertsEventsListSchema = LogsAlertsEventsListParams.omit({ project_id: true }).extend(
    LogsAlertsEventsListQueryParams.shape
)

const logsAlertsEventsList = (): ToolBase<
    typeof LogsAlertsEventsListSchema,
    WithPostHogUrl<Schemas.PaginatedLogsAlertEventList>
> => ({
    name: 'logs-alerts-events-list',
    schema: LogsAlertsEventsListSchema,
    handler: async (context: Context, params: z.infer<typeof LogsAlertsEventsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedLogsAlertEventList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/logs/alerts/${encodeURIComponent(String(params.id))}/events/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'created_at',
                    'kind',
                    'state_before',
                    'state_after',
                    'threshold_breached',
                    'result_count',
                    'error_message',
                    'query_duration_ms',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/logs')
    },
})

const LogsAlertsListSchema = LogsAlertsListQueryParams

const logsAlertsList = (): ToolBase<
    typeof LogsAlertsListSchema,
    WithPostHogUrl<Schemas.PaginatedLogsAlertConfigurationList>
> => ({
    name: 'logs-alerts-list',
    schema: LogsAlertsListSchema,
    handler: async (context: Context, params: z.infer<typeof LogsAlertsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedLogsAlertConfigurationList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/logs/alerts/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'name',
                    'enabled',
                    'state',
                    'threshold_count',
                    'threshold_operator',
                    'window_minutes',
                    'created_at',
                    'updated_at',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/logs')
    },
})

const LogsAlertsPartialUpdateSchema = LogsAlertsPartialUpdateParams.omit({ project_id: true }).extend(
    LogsAlertsPartialUpdateBody.shape
)

const logsAlertsPartialUpdate = (): ToolBase<typeof LogsAlertsPartialUpdateSchema, Schemas.LogsAlertConfiguration> => ({
    name: 'logs-alerts-partial-update',
    schema: LogsAlertsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof LogsAlertsPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.threshold_count !== undefined) {
            body['threshold_count'] = params.threshold_count
        }
        if (params.threshold_operator !== undefined) {
            body['threshold_operator'] = params.threshold_operator
        }
        if (params.window_minutes !== undefined) {
            body['window_minutes'] = params.window_minutes
        }
        if (params.evaluation_periods !== undefined) {
            body['evaluation_periods'] = params.evaluation_periods
        }
        if (params.datapoints_to_alarm !== undefined) {
            body['datapoints_to_alarm'] = params.datapoints_to_alarm
        }
        if (params.cooldown_minutes !== undefined) {
            body['cooldown_minutes'] = params.cooldown_minutes
        }
        if (params.snooze_until !== undefined) {
            body['snooze_until'] = params.snooze_until
        }
        const result = await context.api.request<Schemas.LogsAlertConfiguration>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/logs/alerts/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        const filtered = pickResponseFields(result, [
            'id',
            'name',
            'enabled',
            'state',
            'filters',
            'threshold_count',
            'threshold_operator',
            'window_minutes',
            'check_interval_minutes',
            'evaluation_periods',
            'datapoints_to_alarm',
            'cooldown_minutes',
            'snooze_until',
            'next_check_at',
            'last_notified_at',
            'last_checked_at',
            'consecutive_failures',
            'last_error_message',
            'created_at',
            'updated_at',
        ]) as typeof result
        return filtered
    },
})

const LogsAlertsRetrieveSchema = LogsAlertsRetrieveParams.omit({ project_id: true })

const logsAlertsRetrieve = (): ToolBase<typeof LogsAlertsRetrieveSchema, Schemas.LogsAlertConfiguration> => ({
    name: 'logs-alerts-retrieve',
    schema: LogsAlertsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof LogsAlertsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.LogsAlertConfiguration>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/logs/alerts/${encodeURIComponent(String(params.id))}/`,
        })
        const filtered = pickResponseFields(result, [
            'id',
            'name',
            'enabled',
            'state',
            'filters',
            'threshold_count',
            'threshold_operator',
            'window_minutes',
            'check_interval_minutes',
            'evaluation_periods',
            'datapoints_to_alarm',
            'cooldown_minutes',
            'snooze_until',
            'next_check_at',
            'last_notified_at',
            'last_checked_at',
            'consecutive_failures',
            'last_error_message',
            'created_at',
            'updated_at',
        ]) as typeof result
        return filtered
    },
})

const LogsAlertsSimulateCreateSchema = LogsAlertsSimulateCreateBody

const logsAlertsSimulateCreate = (): ToolBase<
    typeof LogsAlertsSimulateCreateSchema,
    Schemas.LogsAlertSimulateResponse
> => ({
    name: 'logs-alerts-simulate-create',
    schema: LogsAlertsSimulateCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LogsAlertsSimulateCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.threshold_count !== undefined) {
            body['threshold_count'] = params.threshold_count
        }
        if (params.threshold_operator !== undefined) {
            body['threshold_operator'] = params.threshold_operator
        }
        if (params.window_minutes !== undefined) {
            body['window_minutes'] = params.window_minutes
        }
        if (params.check_interval_minutes !== undefined) {
            body['check_interval_minutes'] = params.check_interval_minutes
        }
        if (params.evaluation_periods !== undefined) {
            body['evaluation_periods'] = params.evaluation_periods
        }
        if (params.datapoints_to_alarm !== undefined) {
            body['datapoints_to_alarm'] = params.datapoints_to_alarm
        }
        if (params.cooldown_minutes !== undefined) {
            body['cooldown_minutes'] = params.cooldown_minutes
        }
        if (params.date_from !== undefined) {
            body['date_from'] = params.date_from
        }
        const result = await context.api.request<Schemas.LogsAlertSimulateResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/logs/alerts/simulate/`,
            body,
        })
        const filtered = pickResponseFields(result, [
            'buckets',
            'fire_count',
            'resolve_count',
            'total_buckets',
            'threshold_count',
            'threshold_operator',
        ]) as typeof result
        return filtered
    },
})

const LogsAttributeValuesListSchema = LogsValuesRetrieveQueryParams

const logsAttributeValuesList = (): ToolBase<typeof LogsAttributeValuesListSchema, Schemas._LogsValuesResponse> => ({
    name: 'logs-attribute-values-list',
    schema: LogsAttributeValuesListSchema,
    handler: async (context: Context, params: z.infer<typeof LogsAttributeValuesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas._LogsValuesResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/logs/values/`,
            query: {
                attribute_type: params.attribute_type,
                dateRange: params.dateRange,
                filterGroup: params.filterGroup,
                key: params.key,
                serviceNames: params.serviceNames,
                value: params.value,
            },
        })
        const filtered = pickResponseFields(result, ['results']) as typeof result
        return filtered
    },
})

const LogsAttributesListSchema = LogsAttributesRetrieveQueryParams

const logsAttributesList = (): ToolBase<typeof LogsAttributesListSchema, Schemas._LogsAttributesResponse> => ({
    name: 'logs-attributes-list',
    schema: LogsAttributesListSchema,
    handler: async (context: Context, params: z.infer<typeof LogsAttributesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas._LogsAttributesResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/logs/attributes/`,
            query: {
                attribute_type: params.attribute_type,
                dateRange: params.dateRange,
                filterGroup: params.filterGroup,
                limit: params.limit,
                offset: params.offset,
                search: params.search,
                search_values: params.search_values,
                serviceNames: params.serviceNames,
            },
        })
        const filtered = pickResponseFields(result, ['results', 'count']) as typeof result
        return filtered
    },
})

const LogsCountSchema = LogsCountCreateBody

const logsCount = (): ToolBase<typeof LogsCountSchema, Schemas._LogsCountResponse> => ({
    name: 'logs-count',
    schema: LogsCountSchema,
    handler: async (context: Context, params: z.infer<typeof LogsCountSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        const result = await context.api.request<Schemas._LogsCountResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/logs/count/`,
            body,
        })
        const filtered = pickResponseFields(result, ['count']) as typeof result
        return filtered
    },
})

const LogsCountRangesSchema = LogsCountRangesCreateBody

const logsCountRanges = (): ToolBase<typeof LogsCountRangesSchema, Schemas._LogsCountRangesResponse> => ({
    name: 'logs-count-ranges',
    schema: LogsCountRangesSchema,
    handler: async (context: Context, params: z.infer<typeof LogsCountRangesSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        const result = await context.api.request<Schemas._LogsCountRangesResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/logs/count-ranges/`,
            body,
        })
        const filtered = pickResponseFields(result, ['ranges', 'interval']) as typeof result
        return filtered
    },
})

const LogsServicesCreateSchema = LogsServicesCreateBody

const logsServicesCreate = (): ToolBase<typeof LogsServicesCreateSchema, Schemas._LogsServicesResponse> => ({
    name: 'logs-services-create',
    schema: LogsServicesCreateSchema,
    handler: async (context: Context, params: z.infer<typeof LogsServicesCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        const result = await context.api.request<Schemas._LogsServicesResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/logs/services/`,
            body,
        })
        const filtered = pickResponseFields(result, ['services', 'sparkline']) as typeof result
        return filtered
    },
})

const LogsSparklineQuerySchema = LogsSparklineCreateBody

const logsSparklineQuery = (): ToolBase<typeof LogsSparklineQuerySchema, Schemas._LogsSparklineResponse> => ({
    name: 'logs-sparkline-query',
    schema: LogsSparklineQuerySchema,
    handler: async (context: Context, params: z.infer<typeof LogsSparklineQuerySchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        const result = await context.api.request<Schemas._LogsSparklineResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/logs/sparkline/`,
            body,
        })
        const filtered = pickResponseFields(result, ['results']) as typeof result
        return filtered
    },
})

const QueryLogsSchema = LogsQueryCreateBody

const queryLogs = (): ToolBase<typeof QueryLogsSchema, Schemas._LogsQueryResponse> => ({
    name: 'query-logs',
    schema: QueryLogsSchema,
    handler: async (context: Context, params: z.infer<typeof QueryLogsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        const result = await context.api.request<Schemas._LogsQueryResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/logs/query/`,
            body,
        })
        const filtered = pickResponseFields(result, ['results']) as typeof result
        return filtered
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'logs-alerts-create': logsAlertsCreate,
    'logs-alerts-destinations-create': logsAlertsDestinationsCreate,
    'logs-alerts-destinations-delete-create': logsAlertsDestinationsDeleteCreate,
    'logs-alerts-destroy': logsAlertsDestroy,
    'logs-alerts-events-list': logsAlertsEventsList,
    'logs-alerts-list': logsAlertsList,
    'logs-alerts-partial-update': logsAlertsPartialUpdate,
    'logs-alerts-retrieve': logsAlertsRetrieve,
    'logs-alerts-simulate-create': logsAlertsSimulateCreate,
    'logs-attribute-values-list': logsAttributeValuesList,
    'logs-attributes-list': logsAttributesList,
    'logs-count': logsCount,
    'logs-count-ranges': logsCountRanges,
    'logs-services-create': logsServicesCreate,
    'logs-sparkline-query': logsSparklineQuery,
    'query-logs': queryLogs,
}
