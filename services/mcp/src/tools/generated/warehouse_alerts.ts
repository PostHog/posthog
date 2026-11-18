// AUTO-GENERATED from products/warehouse_sources/mcp/warehouse_alerts.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/warehouse_alerts/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const WarehouseAlertsDestinationsCreateSchema = () => {
    const WarehouseAlertsDestinationsCreateBody = orvalSchemas.WarehouseAlertsDestinationsCreateBody()
    const WarehouseAlertsDestinationsCreateParams = orvalSchemas.WarehouseAlertsDestinationsCreateParams()
    return WarehouseAlertsDestinationsCreateParams.omit({ project_id: true }).extend(
        WarehouseAlertsDestinationsCreateBody.shape
    )
}

const warehouseAlertsDestinationsCreate = (): ToolBase<
    ReturnType<typeof WarehouseAlertsDestinationsCreateSchema>,
    Schemas.WarehouseAlertDestination
> => ({
    name: 'warehouse-alerts-destinations-create',
    schema: WarehouseAlertsDestinationsCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WarehouseAlertsDestinationsCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.type !== undefined) {
            body['type'] = params.type
        }
        if (params.event_kinds !== undefined) {
            body['event_kinds'] = params.event_kinds
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
        if (params.pagerduty_routing_key !== undefined) {
            body['pagerduty_routing_key'] = params.pagerduty_routing_key
        }
        if (params.pagerduty_severity !== undefined) {
            body['pagerduty_severity'] = params.pagerduty_severity
        }
        if (params.pagerduty_region !== undefined) {
            body['pagerduty_region'] = params.pagerduty_region
        }
        const result = await context.api.request<Schemas.WarehouseAlertDestination>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_alerts/${encodeURIComponent(String(params.id))}/destinations/`,
            body,
        })
        return result
    },
})

const WarehouseAlertsDestinationsDeleteSchema = () => {
    const WarehouseAlertsDestinationsDeleteCreateBody = orvalSchemas.WarehouseAlertsDestinationsDeleteCreateBody()
    const WarehouseAlertsDestinationsDeleteCreateParams = orvalSchemas.WarehouseAlertsDestinationsDeleteCreateParams()
    return WarehouseAlertsDestinationsDeleteCreateParams.omit({ project_id: true }).extend(
        WarehouseAlertsDestinationsDeleteCreateBody.shape
    )
}

const warehouseAlertsDestinationsDelete = (): ToolBase<
    ReturnType<typeof WarehouseAlertsDestinationsDeleteSchema>,
    unknown
> => ({
    name: 'warehouse-alerts-destinations-delete',
    schema: WarehouseAlertsDestinationsDeleteSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WarehouseAlertsDestinationsDeleteSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.destination_ids !== undefined) {
            body['destination_ids'] = params.destination_ids
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_alerts/${encodeURIComponent(String(params.id))}/destinations/delete/`,
            body,
        })
        return result
    },
})

const WarehouseAlertsDestinationsListSchema = () => {
    const WarehouseAlertsDestinationsListParams = orvalSchemas.WarehouseAlertsDestinationsListParams()
    return WarehouseAlertsDestinationsListParams.omit({ project_id: true })
}

const warehouseAlertsDestinationsList = (): ToolBase<
    ReturnType<typeof WarehouseAlertsDestinationsListSchema>,
    Schemas.WarehouseAlertDestination[]
> => ({
    name: 'warehouse-alerts-destinations-list',
    schema: WarehouseAlertsDestinationsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof WarehouseAlertsDestinationsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.WarehouseAlertDestination[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/warehouse_alerts/${encodeURIComponent(String(params.id))}/destinations/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'warehouse-alerts-destinations-create': warehouseAlertsDestinationsCreate,
    'warehouse-alerts-destinations-delete': warehouseAlertsDestinationsDelete,
    'warehouse-alerts-destinations-list': warehouseAlertsDestinationsList,
}
