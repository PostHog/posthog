// AUTO-GENERATED from products/web_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    HeatmapsEventsRetrieveQueryParams,
    HeatmapsListQueryParams,
    SavedCreateBody,
    SavedListQueryParams,
    SavedPartialUpdateBody,
    SavedPartialUpdateParams,
    SavedRegenerateCreateParams,
    SavedRetrieveParams,
    WebAnalyticsWeeklyDigestQueryParams,
} from '@/generated/web_analytics/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const HeatmapsEventsSchema = HeatmapsEventsRetrieveQueryParams

const heatmapsEvents = (): ToolBase<typeof HeatmapsEventsSchema, Schemas.HeatmapEventsResponse> => ({
    name: 'heatmaps-events',
    schema: HeatmapsEventsSchema,
    handler: async (context: Context, params: z.infer<typeof HeatmapsEventsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HeatmapEventsResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/heatmaps/events/`,
            query: {
                aggregation: params.aggregation,
                cohort_ids: params.cohort_ids,
                date_from: params.date_from,
                date_to: params.date_to,
                filter_test_accounts: params.filter_test_accounts,
                hide_zero_coordinates: params.hide_zero_coordinates,
                limit: params.limit,
                offset: params.offset,
                points: params.points,
                type: params.type,
                url_exact: params.url_exact,
                url_pattern: params.url_pattern,
                viewport_width_max: params.viewport_width_max,
                viewport_width_min: params.viewport_width_min,
            },
        })
        return result
    },
})

const HeatmapsListSchema = HeatmapsListQueryParams

const heatmapsList = (): ToolBase<typeof HeatmapsListSchema, WithPostHogUrl<Schemas.HeatmapsResponse[]>> => ({
    name: 'heatmaps-list',
    schema: HeatmapsListSchema,
    handler: async (context: Context, params: z.infer<typeof HeatmapsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HeatmapsResponse[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/heatmaps/`,
            query: {
                aggregation: params.aggregation,
                cohort_ids: params.cohort_ids,
                date_from: params.date_from,
                date_to: params.date_to,
                filter_test_accounts: params.filter_test_accounts,
                hide_zero_coordinates: params.hide_zero_coordinates,
                limit: params.limit,
                offset: params.offset,
                type: params.type,
                url_exact: params.url_exact,
                url_pattern: params.url_pattern,
                viewport_width_max: params.viewport_width_max,
                viewport_width_min: params.viewport_width_min,
            },
        })
        return await withPostHogUrl(context, result, '/web')
    },
})

const HeatmapsSavedCreateSchema = SavedCreateBody

const heatmapsSavedCreate = (): ToolBase<typeof HeatmapsSavedCreateSchema, Schemas.HeatmapScreenshotResponse> => ({
    name: 'heatmaps-saved-create',
    schema: HeatmapsSavedCreateSchema,
    handler: async (context: Context, params: z.infer<typeof HeatmapsSavedCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.url !== undefined) {
            body['url'] = params.url
        }
        if (params.data_url !== undefined) {
            body['data_url'] = params.data_url
        }
        if (params.widths !== undefined) {
            body['widths'] = params.widths
        }
        if (params.type !== undefined) {
            body['type'] = params.type
        }
        if (params.block_consent_modals !== undefined) {
            body['block_consent_modals'] = params.block_consent_modals
        }
        const result = await context.api.request<Schemas.HeatmapScreenshotResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/saved/`,
            body,
        })
        return result
    },
})

const HeatmapsSavedGetSchema = SavedRetrieveParams.omit({ project_id: true })

const heatmapsSavedGet = (): ToolBase<typeof HeatmapsSavedGetSchema, Schemas.HeatmapScreenshotResponse> => ({
    name: 'heatmaps-saved-get',
    schema: HeatmapsSavedGetSchema,
    handler: async (context: Context, params: z.infer<typeof HeatmapsSavedGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HeatmapScreenshotResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/saved/${encodeURIComponent(String(params.short_id))}/`,
        })
        return result
    },
})

const HeatmapsSavedListSchema = SavedListQueryParams

const heatmapsSavedList = (): ToolBase<
    typeof HeatmapsSavedListSchema,
    WithPostHogUrl<Schemas.SavedHeatmapListResponse[]>
> => ({
    name: 'heatmaps-saved-list',
    schema: HeatmapsSavedListSchema,
    handler: async (context: Context, params: z.infer<typeof HeatmapsSavedListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SavedHeatmapListResponse[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/saved/`,
            query: {
                created_by: params.created_by,
                limit: params.limit,
                offset: params.offset,
                order: params.order,
                search: params.search,
                status: params.status,
                type: params.type,
            },
        })
        return await withPostHogUrl(context, result, '/web')
    },
})

const HeatmapsSavedRegenerateSchema = SavedRegenerateCreateParams.omit({ project_id: true })

const heatmapsSavedRegenerate = (): ToolBase<
    typeof HeatmapsSavedRegenerateSchema,
    Schemas.HeatmapScreenshotResponse
> => ({
    name: 'heatmaps-saved-regenerate',
    schema: HeatmapsSavedRegenerateSchema,
    handler: async (context: Context, params: z.infer<typeof HeatmapsSavedRegenerateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HeatmapScreenshotResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/saved/${encodeURIComponent(String(params.short_id))}/regenerate/`,
        })
        return result
    },
})

const HeatmapsSavedUpdateSchema = SavedPartialUpdateParams.omit({ project_id: true }).extend(
    SavedPartialUpdateBody.shape
)

const heatmapsSavedUpdate = (): ToolBase<typeof HeatmapsSavedUpdateSchema, Schemas.HeatmapScreenshotResponse> => ({
    name: 'heatmaps-saved-update',
    schema: HeatmapsSavedUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof HeatmapsSavedUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.url !== undefined) {
            body['url'] = params.url
        }
        if (params.data_url !== undefined) {
            body['data_url'] = params.data_url
        }
        if (params.widths !== undefined) {
            body['widths'] = params.widths
        }
        if (params.type !== undefined) {
            body['type'] = params.type
        }
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
        }
        if (params.block_consent_modals !== undefined) {
            body['block_consent_modals'] = params.block_consent_modals
        }
        const result = await context.api.request<Schemas.HeatmapScreenshotResponse>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/saved/${encodeURIComponent(String(params.short_id))}/`,
            body,
        })
        return result
    },
})

const WebAnalyticsWeeklyDigestSchema = WebAnalyticsWeeklyDigestQueryParams

const webAnalyticsWeeklyDigest = (): ToolBase<typeof WebAnalyticsWeeklyDigestSchema, Schemas.WeeklyDigestResponse> => ({
    name: 'web-analytics-weekly-digest',
    schema: WebAnalyticsWeeklyDigestSchema,
    handler: async (context: Context, params: z.infer<typeof WebAnalyticsWeeklyDigestSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.WeeklyDigestResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/web_analytics/weekly_digest/`,
            query: {
                compare: params.compare,
                days: params.days,
            },
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'heatmaps-events': heatmapsEvents,
    'heatmaps-list': heatmapsList,
    'heatmaps-saved-create': heatmapsSavedCreate,
    'heatmaps-saved-get': heatmapsSavedGet,
    'heatmaps-saved-list': heatmapsSavedList,
    'heatmaps-saved-regenerate': heatmapsSavedRegenerate,
    'heatmaps-saved-update': heatmapsSavedUpdate,
    'web-analytics-weekly-digest': webAnalyticsWeeklyDigest,
}
