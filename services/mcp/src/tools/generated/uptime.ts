// AUTO-GENERATED from products/uptime/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    UptimeIncidentsCreateBody,
    UptimeIncidentsDestroyParams,
    UptimeIncidentsListQueryParams,
    UptimeIncidentsPartialUpdateBody,
    UptimeIncidentsPartialUpdateParams,
    UptimeIncidentsReopenCreateParams,
    UptimeIncidentsResolveCreateBody,
    UptimeIncidentsResolveCreateParams,
    UptimeIncidentsRetrieveParams,
    UptimeMonitorsBulkCreateCreateBody,
    UptimeMonitorsBulkCreateCreateQueryParams,
    UptimeMonitorsCreateBody,
    UptimeMonitorsDestroyParams,
    UptimeMonitorsListQueryParams,
    UptimeMonitorsPartialUpdateBody,
    UptimeMonitorsPartialUpdateParams,
    UptimeMonitorsPingNowCreateParams,
    UptimeMonitorsPingsListParams,
    UptimeMonitorsPingsListQueryParams,
    UptimeMonitorsReorderCreateBody,
    UptimeMonitorsRetrieveParams,
    UptimeMonitorsSuggestedUrlsListQueryParams,
    UptimeMonitorsSummaryListQueryParams,
    UptimeStatusPagesDestroyParams,
    UptimeStatusPagesListQueryParams,
    UptimeStatusPagesPartialUpdateBody,
    UptimeStatusPagesPartialUpdateParams,
    UptimeStatusPagesPublishCreateParams,
    UptimeStatusPagesRetrieveParams,
    UptimeStatusPagesUnpublishCreateParams,
} from '@/generated/uptime/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const MonitorListSchema = UptimeMonitorsListQueryParams

const monitorList = (): ToolBase<typeof MonitorListSchema, WithPostHogUrl<Schemas.PaginatedMonitorDTOList>> => ({
    name: 'monitor-list',
    schema: MonitorListSchema,
    handler: async (context: Context, params: z.infer<typeof MonitorListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedMonitorDTOList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/uptime/monitors/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(
            context,
            {
                ...result,
                results: await Promise.all(
                    (result.results ?? []).map((item) => withPostHogUrl(context, item, `/uptime/${item.id}`))
                ),
            },
            '/uptime'
        )
    },
})

const MonitorSummaryListSchema = UptimeMonitorsSummaryListQueryParams

const monitorSummaryList = (): ToolBase<
    typeof MonitorSummaryListSchema,
    WithPostHogUrl<Schemas.PaginatedMonitorSummaryDTOList>
> => ({
    name: 'monitor-summary-list',
    schema: MonitorSummaryListSchema,
    handler: async (context: Context, params: z.infer<typeof MonitorSummaryListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedMonitorSummaryDTOList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/uptime/monitors/summary/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/uptime')
    },
})

const MonitorGetSchema = UptimeMonitorsRetrieveParams.omit({ project_id: true })

const monitorGet = (): ToolBase<typeof MonitorGetSchema, WithPostHogUrl<Schemas.MonitorSummaryDTO>> => ({
    name: 'monitor-get',
    schema: MonitorGetSchema,
    handler: async (context: Context, params: z.infer<typeof MonitorGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.MonitorSummaryDTO>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/uptime/monitors/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/uptime/${result.id}`)
    },
})

const MonitorPingsSchema = UptimeMonitorsPingsListParams.omit({ project_id: true }).extend(
    UptimeMonitorsPingsListQueryParams.shape
)

const monitorPings = (): ToolBase<typeof MonitorPingsSchema, WithPostHogUrl<Schemas.PaginatedPingDTOList>> => ({
    name: 'monitor-pings',
    schema: MonitorPingsSchema,
    handler: async (context: Context, params: z.infer<typeof MonitorPingsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedPingDTOList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/uptime/monitors/${encodeURIComponent(String(params.id))}/pings/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, `/uptime/${result.id}`)
    },
})

const MonitorSuggestedUrlsSchema = UptimeMonitorsSuggestedUrlsListQueryParams

const monitorSuggestedUrls = (): ToolBase<typeof MonitorSuggestedUrlsSchema, Schemas.PaginatedSuggestedUrlDTOList> => ({
    name: 'monitor-suggested-urls',
    schema: MonitorSuggestedUrlsSchema,
    handler: async (context: Context, params: z.infer<typeof MonitorSuggestedUrlsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedSuggestedUrlDTOList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/uptime/monitors/suggested_urls/`,
            query: {
                days: params.days,
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

const IncidentListSchema = UptimeIncidentsListQueryParams

const incidentList = (): ToolBase<typeof IncidentListSchema, WithPostHogUrl<Schemas.PaginatedIncidentDTOList>> => ({
    name: 'incident-list',
    schema: IncidentListSchema,
    handler: async (context: Context, params: z.infer<typeof IncidentListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedIncidentDTOList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/uptime/incidents/`,
            query: {
                limit: params.limit,
                monitor_id: params.monitor_id,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(
            context,
            {
                ...result,
                results: await Promise.all(
                    (result.results ?? []).map((item) => withPostHogUrl(context, item, `/uptime/${item.id}`))
                ),
            },
            '/uptime'
        )
    },
})

const IncidentGetSchema = UptimeIncidentsRetrieveParams.omit({ project_id: true })

const incidentGet = (): ToolBase<typeof IncidentGetSchema, WithPostHogUrl<Schemas.IncidentDTO>> => ({
    name: 'incident-get',
    schema: IncidentGetSchema,
    handler: async (context: Context, params: z.infer<typeof IncidentGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.IncidentDTO>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/uptime/incidents/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/uptime/${result.id}`)
    },
})

const StatusPageListSchema = UptimeStatusPagesListQueryParams

const statusPageList = (): ToolBase<
    typeof StatusPageListSchema,
    WithPostHogUrl<Schemas.PaginatedStatusPageDTOList>
> => ({
    name: 'status-page-list',
    schema: StatusPageListSchema,
    handler: async (context: Context, params: z.infer<typeof StatusPageListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedStatusPageDTOList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/uptime/status_pages/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(
            context,
            {
                ...result,
                results: await Promise.all(
                    (result.results ?? []).map((item) => withPostHogUrl(context, item, `/uptime/${item.id}`))
                ),
            },
            '/uptime'
        )
    },
})

const StatusPageGetSchema = UptimeStatusPagesRetrieveParams.omit({ project_id: true })

const statusPageGet = (): ToolBase<typeof StatusPageGetSchema, WithPostHogUrl<Schemas.StatusPageDTO>> => ({
    name: 'status-page-get',
    schema: StatusPageGetSchema,
    handler: async (context: Context, params: z.infer<typeof StatusPageGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.StatusPageDTO>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/uptime/status_pages/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/uptime/${result.id}`)
    },
})

const MonitorCreateSchema = UptimeMonitorsCreateBody

const monitorCreate = (): ToolBase<typeof MonitorCreateSchema, WithPostHogUrl<Schemas.MonitorDTO>> => ({
    name: 'monitor-create',
    schema: MonitorCreateSchema,
    handler: async (context: Context, params: z.infer<typeof MonitorCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.url !== undefined) {
            body['url'] = params.url
        }
        if (params.mode !== undefined) {
            body['mode'] = params.mode
        }
        const result = await context.api.request<Schemas.MonitorDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/uptime/monitors/`,
            body,
        })
        return await withPostHogUrl(context, result, `/uptime/${result.id}`)
    },
})

const MonitorUpdateSchema = UptimeMonitorsPartialUpdateParams.omit({ project_id: true }).extend(
    UptimeMonitorsPartialUpdateBody.shape
)

const monitorUpdate = (): ToolBase<typeof MonitorUpdateSchema, WithPostHogUrl<Schemas.MonitorDTO>> => ({
    name: 'monitor-update',
    schema: MonitorUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof MonitorUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.url !== undefined) {
            body['url'] = params.url
        }
        if (params.mode !== undefined) {
            body['mode'] = params.mode
        }
        const result = await context.api.request<Schemas.MonitorDTO>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/uptime/monitors/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/uptime/${result.id}`)
    },
})

const MonitorDeleteSchema = UptimeMonitorsDestroyParams.omit({ project_id: true })

const monitorDelete = (): ToolBase<typeof MonitorDeleteSchema, unknown> => ({
    name: 'monitor-delete',
    schema: MonitorDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof MonitorDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/uptime/monitors/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/uptime/${result.id}`)
    },
})

const MonitorPingNowSchema = UptimeMonitorsPingNowCreateParams.omit({ project_id: true })

const monitorPingNow = (): ToolBase<typeof MonitorPingNowSchema, unknown> => ({
    name: 'monitor-ping-now',
    schema: MonitorPingNowSchema,
    handler: async (context: Context, params: z.infer<typeof MonitorPingNowSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/uptime/monitors/${encodeURIComponent(String(params.id))}/ping_now/`,
        })
        return await withPostHogUrl(context, result, `/uptime/${result.id}`)
    },
})

const MonitorBulkCreateSchema = UptimeMonitorsBulkCreateCreateQueryParams.extend(
    UptimeMonitorsBulkCreateCreateBody.shape
)

const monitorBulkCreate = (): ToolBase<typeof MonitorBulkCreateSchema, Schemas.PaginatedMonitorDTOList> => ({
    name: 'monitor-bulk-create',
    schema: MonitorBulkCreateSchema,
    handler: async (context: Context, params: z.infer<typeof MonitorBulkCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.monitors !== undefined) {
            body['monitors'] = params.monitors
        }
        const result = await context.api.request<Schemas.PaginatedMonitorDTOList>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/uptime/monitors/bulk_create/`,
            body,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

const MonitorReorderSchema = UptimeMonitorsReorderCreateBody

const monitorReorder = (): ToolBase<typeof MonitorReorderSchema, unknown> => ({
    name: 'monitor-reorder',
    schema: MonitorReorderSchema,
    handler: async (context: Context, params: z.infer<typeof MonitorReorderSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.ordered_ids !== undefined) {
            body['ordered_ids'] = params.ordered_ids
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/uptime/monitors/reorder/`,
            body,
        })
        return result
    },
})

const IncidentCreateSchema = UptimeIncidentsCreateBody

const incidentCreate = (): ToolBase<typeof IncidentCreateSchema, WithPostHogUrl<Schemas.IncidentDTO>> => ({
    name: 'incident-create',
    schema: IncidentCreateSchema,
    handler: async (context: Context, params: z.infer<typeof IncidentCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.monitor_id !== undefined) {
            body['monitor_id'] = params.monitor_id
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.started_at !== undefined) {
            body['started_at'] = params.started_at
        }
        if (params.resolved_at !== undefined) {
            body['resolved_at'] = params.resolved_at
        }
        if (params.resolution_note !== undefined) {
            body['resolution_note'] = params.resolution_note
        }
        const result = await context.api.request<Schemas.IncidentDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/uptime/incidents/`,
            body,
        })
        return await withPostHogUrl(context, result, `/uptime/${result.id}`)
    },
})

const IncidentUpdateSchema = UptimeIncidentsPartialUpdateParams.omit({ project_id: true }).extend(
    UptimeIncidentsPartialUpdateBody.shape
)

const incidentUpdate = (): ToolBase<typeof IncidentUpdateSchema, WithPostHogUrl<Schemas.IncidentDTO>> => ({
    name: 'incident-update',
    schema: IncidentUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof IncidentUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.started_at !== undefined) {
            body['started_at'] = params.started_at
        }
        if (params.resolved_at !== undefined) {
            body['resolved_at'] = params.resolved_at
        }
        if (params.resolution_note !== undefined) {
            body['resolution_note'] = params.resolution_note
        }
        const result = await context.api.request<Schemas.IncidentDTO>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/uptime/incidents/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/uptime/${result.id}`)
    },
})

const IncidentDeleteSchema = UptimeIncidentsDestroyParams.omit({ project_id: true })

const incidentDelete = (): ToolBase<typeof IncidentDeleteSchema, unknown> => ({
    name: 'incident-delete',
    schema: IncidentDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof IncidentDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/uptime/incidents/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/uptime/${result.id}`)
    },
})

const IncidentResolveSchema = UptimeIncidentsResolveCreateParams.omit({ project_id: true }).extend(
    UptimeIncidentsResolveCreateBody.shape
)

const incidentResolve = (): ToolBase<typeof IncidentResolveSchema, WithPostHogUrl<Schemas.IncidentDTO>> => ({
    name: 'incident-resolve',
    schema: IncidentResolveSchema,
    handler: async (context: Context, params: z.infer<typeof IncidentResolveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.resolution_note !== undefined) {
            body['resolution_note'] = params.resolution_note
        }
        const result = await context.api.request<Schemas.IncidentDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/uptime/incidents/${encodeURIComponent(String(params.id))}/resolve/`,
            body,
        })
        return await withPostHogUrl(context, result, `/uptime/${result.id}`)
    },
})

const IncidentReopenSchema = UptimeIncidentsReopenCreateParams.omit({ project_id: true })

const incidentReopen = (): ToolBase<typeof IncidentReopenSchema, WithPostHogUrl<Schemas.IncidentDTO>> => ({
    name: 'incident-reopen',
    schema: IncidentReopenSchema,
    handler: async (context: Context, params: z.infer<typeof IncidentReopenSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.IncidentDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/uptime/incidents/${encodeURIComponent(String(params.id))}/reopen/`,
        })
        return await withPostHogUrl(context, result, `/uptime/${result.id}`)
    },
})

const StatusPageCreateSchema = z.object({})

const statusPageCreate = (): ToolBase<typeof StatusPageCreateSchema, WithPostHogUrl<Schemas.StatusPageDTO>> => ({
    name: 'status-page-create',
    schema: StatusPageCreateSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof StatusPageCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.StatusPageDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/uptime/status_pages/`,
        })
        return await withPostHogUrl(context, result, `/uptime/${result.id}`)
    },
})

const StatusPageUpdateSchema = UptimeStatusPagesPartialUpdateParams.omit({ project_id: true }).extend(
    UptimeStatusPagesPartialUpdateBody.shape
)

const statusPageUpdate = (): ToolBase<typeof StatusPageUpdateSchema, WithPostHogUrl<Schemas.StatusPageDTO>> => ({
    name: 'status-page-update',
    schema: StatusPageUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof StatusPageUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.title !== undefined) {
            body['title'] = params.title
        }
        if (params.slug !== undefined) {
            body['slug'] = params.slug
        }
        if (params.monitor_ids !== undefined) {
            body['monitor_ids'] = params.monitor_ids
        }
        const result = await context.api.request<Schemas.StatusPageDTO>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/uptime/status_pages/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/uptime/${result.id}`)
    },
})

const StatusPageDeleteSchema = UptimeStatusPagesDestroyParams.omit({ project_id: true })

const statusPageDelete = (): ToolBase<typeof StatusPageDeleteSchema, unknown> => ({
    name: 'status-page-delete',
    schema: StatusPageDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof StatusPageDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/uptime/status_pages/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/uptime/${result.id}`)
    },
})

const StatusPagePublishSchema = UptimeStatusPagesPublishCreateParams.omit({ project_id: true })

const statusPagePublish = (): ToolBase<typeof StatusPagePublishSchema, WithPostHogUrl<Schemas.StatusPageDTO>> => ({
    name: 'status-page-publish',
    schema: StatusPagePublishSchema,
    handler: async (context: Context, params: z.infer<typeof StatusPagePublishSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.StatusPageDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/uptime/status_pages/${encodeURIComponent(String(params.id))}/publish/`,
        })
        return await withPostHogUrl(context, result, `/uptime/${result.id}`)
    },
})

const StatusPageUnpublishSchema = UptimeStatusPagesUnpublishCreateParams.omit({ project_id: true })

const statusPageUnpublish = (): ToolBase<typeof StatusPageUnpublishSchema, WithPostHogUrl<Schemas.StatusPageDTO>> => ({
    name: 'status-page-unpublish',
    schema: StatusPageUnpublishSchema,
    handler: async (context: Context, params: z.infer<typeof StatusPageUnpublishSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.StatusPageDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/uptime/status_pages/${encodeURIComponent(String(params.id))}/unpublish/`,
        })
        return await withPostHogUrl(context, result, `/uptime/${result.id}`)
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'monitor-list': monitorList,
    'monitor-summary-list': monitorSummaryList,
    'monitor-get': monitorGet,
    'monitor-pings': monitorPings,
    'monitor-suggested-urls': monitorSuggestedUrls,
    'incident-list': incidentList,
    'incident-get': incidentGet,
    'status-page-list': statusPageList,
    'status-page-get': statusPageGet,
    'monitor-create': monitorCreate,
    'monitor-update': monitorUpdate,
    'monitor-delete': monitorDelete,
    'monitor-ping-now': monitorPingNow,
    'monitor-bulk-create': monitorBulkCreate,
    'monitor-reorder': monitorReorder,
    'incident-create': incidentCreate,
    'incident-update': incidentUpdate,
    'incident-delete': incidentDelete,
    'incident-resolve': incidentResolve,
    'incident-reopen': incidentReopen,
    'status-page-create': statusPageCreate,
    'status-page-update': statusPageUpdate,
    'status-page-delete': statusPageDelete,
    'status-page-publish': statusPagePublish,
    'status-page-unpublish': statusPageUnpublish,
}
