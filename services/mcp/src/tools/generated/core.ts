// AUTO-GENERATED from services/mcp/definitions/core.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    SubscriptionsCreateBody,
    SubscriptionsDeliveriesListParams,
    SubscriptionsDeliveriesListQueryParams,
    SubscriptionsDeliveriesRetrieveParams,
    SubscriptionsListQueryParams,
    SubscriptionsPartialUpdateBody,
    SubscriptionsPartialUpdateParams,
    SubscriptionsRetrieveParams,
    SubscriptionsTestDeliveryCreateParams,
} from '@/generated/core/api'
import { withPostHogUrl, omitResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const SubscriptionsListSchema = SubscriptionsListQueryParams

const subscriptionsList = (): ToolBase<
    typeof SubscriptionsListSchema,
    WithPostHogUrl<Schemas.PaginatedSubscriptionList>
> => ({
    name: 'subscriptions-list',
    schema: SubscriptionsListSchema,
    handler: async (context: Context, params: z.infer<typeof SubscriptionsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedSubscriptionList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/subscriptions/`,
            query: {
                created_by: params.created_by,
                dashboard: params.dashboard,
                insight: params.insight,
                limit: params.limit,
                offset: params.offset,
                ordering: params.ordering,
                resource_type: params.resource_type,
                search: params.search,
                target_type: params.target_type,
            },
        })
        return await withPostHogUrl(context, result, '/')
    },
})

const SubscriptionsCreateSchema = SubscriptionsCreateBody

const subscriptionsCreate = (): ToolBase<typeof SubscriptionsCreateSchema, Schemas.Subscription> => ({
    name: 'subscriptions-create',
    schema: SubscriptionsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof SubscriptionsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.dashboard !== undefined) {
            body['dashboard'] = params.dashboard
        }
        if (params.insight !== undefined) {
            body['insight'] = params.insight
        }
        if (params.dashboard_export_insights !== undefined) {
            body['dashboard_export_insights'] = params.dashboard_export_insights
        }
        if (params.target_type !== undefined) {
            body['target_type'] = params.target_type
        }
        if (params.target_value !== undefined) {
            body['target_value'] = params.target_value
        }
        if (params.frequency !== undefined) {
            body['frequency'] = params.frequency
        }
        if (params.interval !== undefined) {
            body['interval'] = params.interval
        }
        if (params.byweekday !== undefined) {
            body['byweekday'] = params.byweekday
        }
        if (params.bysetpos !== undefined) {
            body['bysetpos'] = params.bysetpos
        }
        if (params.count !== undefined) {
            body['count'] = params.count
        }
        if (params.start_date !== undefined) {
            body['start_date'] = params.start_date
        }
        if (params.until_date !== undefined) {
            body['until_date'] = params.until_date
        }
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
        }
        if (params.title !== undefined) {
            body['title'] = params.title
        }
        if (params.integration_id !== undefined) {
            body['integration_id'] = params.integration_id
        }
        if (params.invite_message !== undefined) {
            body['invite_message'] = params.invite_message
        }
        if (params.summary_enabled !== undefined) {
            body['summary_enabled'] = params.summary_enabled
        }
        if (params.summary_prompt_guide !== undefined) {
            body['summary_prompt_guide'] = params.summary_prompt_guide
        }
        const result = await context.api.request<Schemas.Subscription>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/subscriptions/`,
            body,
        })
        return result
    },
})

const SubscriptionsRetrieveSchema = SubscriptionsRetrieveParams.omit({ project_id: true })

const subscriptionsRetrieve = (): ToolBase<typeof SubscriptionsRetrieveSchema, Schemas.Subscription> => ({
    name: 'subscriptions-retrieve',
    schema: SubscriptionsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof SubscriptionsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Subscription>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/subscriptions/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const SubscriptionsPartialUpdateSchema = SubscriptionsPartialUpdateParams.omit({ project_id: true }).extend(
    SubscriptionsPartialUpdateBody.shape
)

const subscriptionsPartialUpdate = (): ToolBase<typeof SubscriptionsPartialUpdateSchema, Schemas.Subscription> => ({
    name: 'subscriptions-partial-update',
    schema: SubscriptionsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof SubscriptionsPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.dashboard !== undefined) {
            body['dashboard'] = params.dashboard
        }
        if (params.insight !== undefined) {
            body['insight'] = params.insight
        }
        if (params.dashboard_export_insights !== undefined) {
            body['dashboard_export_insights'] = params.dashboard_export_insights
        }
        if (params.target_type !== undefined) {
            body['target_type'] = params.target_type
        }
        if (params.target_value !== undefined) {
            body['target_value'] = params.target_value
        }
        if (params.frequency !== undefined) {
            body['frequency'] = params.frequency
        }
        if (params.interval !== undefined) {
            body['interval'] = params.interval
        }
        if (params.byweekday !== undefined) {
            body['byweekday'] = params.byweekday
        }
        if (params.bysetpos !== undefined) {
            body['bysetpos'] = params.bysetpos
        }
        if (params.count !== undefined) {
            body['count'] = params.count
        }
        if (params.start_date !== undefined) {
            body['start_date'] = params.start_date
        }
        if (params.until_date !== undefined) {
            body['until_date'] = params.until_date
        }
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
        }
        if (params.title !== undefined) {
            body['title'] = params.title
        }
        if (params.integration_id !== undefined) {
            body['integration_id'] = params.integration_id
        }
        if (params.invite_message !== undefined) {
            body['invite_message'] = params.invite_message
        }
        if (params.summary_enabled !== undefined) {
            body['summary_enabled'] = params.summary_enabled
        }
        if (params.summary_prompt_guide !== undefined) {
            body['summary_prompt_guide'] = params.summary_prompt_guide
        }
        const result = await context.api.request<Schemas.Subscription>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/subscriptions/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const SubscriptionsTestDeliveryCreateSchema = SubscriptionsTestDeliveryCreateParams.omit({ project_id: true })

const subscriptionsTestDeliveryCreate = (): ToolBase<typeof SubscriptionsTestDeliveryCreateSchema, unknown> => ({
    name: 'subscriptions-test-delivery-create',
    schema: SubscriptionsTestDeliveryCreateSchema,
    handler: async (context: Context, params: z.infer<typeof SubscriptionsTestDeliveryCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/subscriptions/${encodeURIComponent(String(params.id))}/test-delivery/`,
        })
        return result
    },
})

const SubscriptionsDeliveriesListSchema = SubscriptionsDeliveriesListParams.omit({ project_id: true }).extend(
    SubscriptionsDeliveriesListQueryParams.shape
)

const subscriptionsDeliveriesList = (): ToolBase<
    typeof SubscriptionsDeliveriesListSchema,
    WithPostHogUrl<Schemas.PaginatedSubscriptionDeliveryList>
> => ({
    name: 'subscriptions-deliveries-list',
    schema: SubscriptionsDeliveriesListSchema,
    handler: async (context: Context, params: z.infer<typeof SubscriptionsDeliveriesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedSubscriptionDeliveryList>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/subscriptions/${encodeURIComponent(String(params.subscription_id))}/deliveries/`,
            query: {
                cursor: params.cursor,
                status: params.status,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                omitResponseFields(item, ['content_snapshot', 'recipient_results', 'error'])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/')
    },
})

const SubscriptionsDeliveriesRetrieveSchema = SubscriptionsDeliveriesRetrieveParams.omit({ project_id: true })

const subscriptionsDeliveriesRetrieve = (): ToolBase<
    typeof SubscriptionsDeliveriesRetrieveSchema,
    Schemas.SubscriptionDelivery
> => ({
    name: 'subscriptions-deliveries-retrieve',
    schema: SubscriptionsDeliveriesRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof SubscriptionsDeliveriesRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SubscriptionDelivery>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/subscriptions/${encodeURIComponent(String(params.subscription_id))}/deliveries/${encodeURIComponent(String(params.id))}/`,
        })
        const filtered = omitResponseFields(result, ['content_snapshot', 'recipient_results', 'error']) as typeof result
        return filtered
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'subscriptions-list': subscriptionsList,
    'subscriptions-create': subscriptionsCreate,
    'subscriptions-retrieve': subscriptionsRetrieve,
    'subscriptions-partial-update': subscriptionsPartialUpdate,
    'subscriptions-test-delivery-create': subscriptionsTestDeliveryCreate,
    'subscriptions-deliveries-list': subscriptionsDeliveriesList,
    'subscriptions-deliveries-retrieve': subscriptionsDeliveriesRetrieve,
}
