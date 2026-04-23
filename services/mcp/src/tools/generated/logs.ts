// AUTO-GENERATED from products/logs/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    LogsAlertsCreateBody,
    LogsAlertsDestroyParams,
    LogsAlertsListQueryParams,
    LogsAlertsPartialUpdateBody,
    LogsAlertsPartialUpdateParams,
    LogsAlertsRetrieveParams,
    LogsAttributesRetrieveQueryParams,
    LogsQueryCreateBody,
    LogsSparklineCreateBody,
    LogsValuesRetrieveQueryParams,
} from '@/generated/logs/api'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

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
                serviceNames: params.serviceNames,
            },
        })
        const filtered = pickResponseFields(result, ['results', 'count']) as typeof result
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

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'query-logs': queryLogs,
    'logs-attributes-list': logsAttributesList,
    'logs-attribute-values-list': logsAttributeValuesList,
    'logs-alerts-list': logsAlertsList,
    'logs-alerts-create': logsAlertsCreate,
    'logs-alerts-retrieve': logsAlertsRetrieve,
    'logs-alerts-partial-update': logsAlertsPartialUpdate,
    'logs-alerts-destroy': logsAlertsDestroy,
    'logs-sparkline-query': logsSparklineQuery,
}
