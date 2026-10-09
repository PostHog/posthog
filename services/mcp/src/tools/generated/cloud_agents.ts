// AUTO-GENERATED from products/cloud_agents/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/cloud_agents/api'
import { withPostHogUrl, omitResponseFields, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const CloudAgentsCatalogSchema = () => z.object({})

const cloudAgentsCatalog = (): ToolBase<ReturnType<typeof CloudAgentsCatalogSchema>, Schemas.CloudAgentCatalog> => ({
    name: 'cloud-agents-catalog',
    schema: CloudAgentsCatalogSchema(),
    handler: async (context: Context, _params: z.infer<ReturnType<typeof CloudAgentsCatalogSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.CloudAgentCatalog>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/cloud_agents/catalog/`,
        })
        return result
    },
})

const CloudAgentsEstimateSchema = () => {
    const CloudAgentsEstimateRetrieveQueryParams = orvalSchemas.CloudAgentsEstimateRetrieveQueryParams()
    return CloudAgentsEstimateRetrieveQueryParams
}

const cloudAgentsEstimate = (): ToolBase<ReturnType<typeof CloudAgentsEstimateSchema>, Schemas.CloudAgentEstimate> => ({
    name: 'cloud-agents-estimate',
    schema: CloudAgentsEstimateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CloudAgentsEstimateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.CloudAgentEstimate>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/cloud_agents/estimate/`,
            query: {
                minutes: params.minutes,
                size: params.size,
            },
        })
        return result
    },
})

const CloudAgentsPresetCreateSchema = () => {
    const CloudAgentsPresetsCreateBody = orvalSchemas.CloudAgentsPresetsCreateBody()
    return CloudAgentsPresetsCreateBody
}

const cloudAgentsPresetCreate = (): ToolBase<
    ReturnType<typeof CloudAgentsPresetCreateSchema>,
    WithPostHogUrl<Schemas.CloudAgentPreset>
> => ({
    name: 'cloud-agents-preset-create',
    schema: CloudAgentsPresetCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CloudAgentsPresetCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.repositories !== undefined) {
            body['repositories'] = params.repositories
        }
        if (params.model !== undefined) {
            body['model'] = params.model
        }
        if (params.reasoning_effort !== undefined) {
            body['reasoning_effort'] = params.reasoning_effort
        }
        if (params.size !== undefined) {
            body['size'] = params.size
        }
        if (params.inference !== undefined) {
            body['inference'] = params.inference
        }
        if (params.instructions !== undefined) {
            body['instructions'] = params.instructions
        }
        if (params.create_pr !== undefined) {
            body['create_pr'] = params.create_pr
        }
        if (params.idle_minutes !== undefined) {
            body['idle_minutes'] = params.idle_minutes
        }
        if (params.output_schema !== undefined) {
            body['output_schema'] = params.output_schema
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        const result = await context.api.request<Schemas.CloudAgentPreset>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/cloud_agents/presets/`,
            body,
        })
        return await withPostHogUrl(context, result, `/cloud-agents/presets/${result.id}`)
    },
})

const CloudAgentsPresetGetSchema = () => {
    const CloudAgentsPresetsRetrieveParams = orvalSchemas.CloudAgentsPresetsRetrieveParams()
    return CloudAgentsPresetsRetrieveParams.omit({ project_id: true }).extend({
        id: CloudAgentsPresetsRetrieveParams.shape['id'].describe(
            'ID of the preset (a UUID). A preset name is not accepted here.'
        ),
    })
}

const cloudAgentsPresetGet = (): ToolBase<
    ReturnType<typeof CloudAgentsPresetGetSchema>,
    WithPostHogUrl<Schemas.CloudAgentPreset>
> => ({
    name: 'cloud-agents-preset-get',
    schema: CloudAgentsPresetGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CloudAgentsPresetGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.CloudAgentPreset>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/cloud_agents/presets/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/cloud-agents/presets/${result.id}`)
    },
})

const CloudAgentsPresetListSchema = () => {
    const CloudAgentsPresetsListQueryParams = orvalSchemas.CloudAgentsPresetsListQueryParams()
    return CloudAgentsPresetsListQueryParams
}

const cloudAgentsPresetList = (): ToolBase<
    ReturnType<typeof CloudAgentsPresetListSchema>,
    WithPostHogUrl<Schemas.PaginatedCloudAgentPresetList>
> => ({
    name: 'cloud-agents-preset-list',
    schema: CloudAgentsPresetListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CloudAgentsPresetListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedCloudAgentPresetList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/cloud_agents/presets/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                omitResponseFields(item, ['instructions', 'created_by'])
            ),
        } as typeof result
        return await withPostHogUrl(
            context,
            {
                ...filtered,
                results: await Promise.all(
                    (filtered.results ?? []).map((item) =>
                        withPostHogUrl(context, item, `/cloud-agents/presets/${item.id}`)
                    )
                ),
            },
            '/cloud-agents'
        )
    },
})

const CloudAgentsRunCancelSchema = () => {
    const CloudAgentsRunsCancelCreateParams = orvalSchemas.CloudAgentsRunsCancelCreateParams()
    return CloudAgentsRunsCancelCreateParams.omit({ project_id: true }).extend({
        id: CloudAgentsRunsCancelCreateParams.shape['id'].describe('ID of the run to cancel (a UUID).'),
    })
}

const cloudAgentsRunCancel = (): ToolBase<ReturnType<typeof CloudAgentsRunCancelSchema>, Schemas.CloudAgentRun> => ({
    name: 'cloud-agents-run-cancel',
    schema: CloudAgentsRunCancelSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CloudAgentsRunCancelSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.CloudAgentRun>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/cloud_agents/runs/${encodeURIComponent(String(params.id))}/cancel/`,
        })
        const filtered = pickResponseFields(result, [
            'id',
            'status',
            'status_reason',
            'status_detail',
            'ended_at',
            'result',
            'cost',
        ]) as typeof result
        return filtered
    },
})

const CloudAgentsRunCreateSchema = () => {
    const CloudAgentsRunsCreateBody = orvalSchemas.CloudAgentsRunsCreateBody()
    return CloudAgentsRunsCreateBody.extend({
        prompt: CloudAgentsRunsCreateBody.shape['prompt'].describe(
            'The task for the agent, in plain language. Say what to change and how to know it is done. The agent sees only this text, the instructions, and the repository.'
        ),
        size: CloudAgentsRunsCreateBody.shape['size'].describe(
            'Sandbox size, as `<vCPU>x<memory in GiB>`. A larger size costs more per second. Leave it out to use the default of the preset or the project. See cloud-agents-catalog for prices.'
        ),
        model: CloudAgentsRunsCreateBody.shape['model'].describe(
            'Model ID from cloud-agents-catalog. Leave it out to use the default of the preset or the project.'
        ),
    })
}

const cloudAgentsRunCreate = (): ToolBase<
    ReturnType<typeof CloudAgentsRunCreateSchema>,
    WithPostHogUrl<Schemas.CloudAgentRun>
> => ({
    name: 'cloud-agents-run-create',
    schema: CloudAgentsRunCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CloudAgentsRunCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.repositories !== undefined) {
            body['repositories'] = params.repositories
        }
        if (params.model !== undefined) {
            body['model'] = params.model
        }
        if (params.reasoning_effort !== undefined) {
            body['reasoning_effort'] = params.reasoning_effort
        }
        if (params.size !== undefined) {
            body['size'] = params.size
        }
        if (params.inference !== undefined) {
            body['inference'] = params.inference
        }
        if (params.instructions !== undefined) {
            body['instructions'] = params.instructions
        }
        if (params.create_pr !== undefined) {
            body['create_pr'] = params.create_pr
        }
        if (params.idle_minutes !== undefined) {
            body['idle_minutes'] = params.idle_minutes
        }
        if (params.output_schema !== undefined) {
            body['output_schema'] = params.output_schema
        }
        if (params.prompt !== undefined) {
            body['prompt'] = params.prompt
        }
        if (params.preset !== undefined) {
            body['preset'] = params.preset
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.metadata !== undefined) {
            body['metadata'] = params.metadata
        }
        const result = await context.api.request<Schemas.CloudAgentRun>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/cloud_agents/runs/`,
            body,
        })
        const filtered = pickResponseFields(result, [
            'id',
            'status',
            'created_at',
            'repositories',
            'preset',
            'config.model',
            'config.size',
            'config.inference',
            'config.reasoning_effort',
            'config.idle_minutes',
            'config.create_pr',
            'tags',
        ]) as typeof result
        return await withPostHogUrl(context, filtered, `/cloud-agents/runs/${filtered.id}`)
    },
})

const CloudAgentsRunEventsSchema = () => {
    const CloudAgentsRunsEventsRetrieveParams = orvalSchemas.CloudAgentsRunsEventsRetrieveParams()
    return CloudAgentsRunsEventsRetrieveParams.omit({ project_id: true }).extend({
        id: CloudAgentsRunsEventsRetrieveParams.shape['id'].describe('ID of the run (a UUID).'),
    })
}

const cloudAgentsRunEvents = (): ToolBase<
    ReturnType<typeof CloudAgentsRunEventsSchema>,
    Schemas.CloudAgentRunEvents
> => ({
    name: 'cloud-agents-run-events',
    schema: CloudAgentsRunEventsSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CloudAgentsRunEventsSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.CloudAgentRunEvents>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/cloud_agents/runs/${encodeURIComponent(String(params.id))}/events/`,
        })
        return result
    },
})

const CloudAgentsRunGetSchema = () => {
    const CloudAgentsRunsRetrieveParams = orvalSchemas.CloudAgentsRunsRetrieveParams()
    return CloudAgentsRunsRetrieveParams.omit({ project_id: true }).extend({
        id: CloudAgentsRunsRetrieveParams.shape['id'].describe('ID of the run (a UUID).'),
    })
}

const cloudAgentsRunGet = (): ToolBase<
    ReturnType<typeof CloudAgentsRunGetSchema>,
    WithPostHogUrl<Schemas.CloudAgentRun>
> => ({
    name: 'cloud-agents-run-get',
    schema: CloudAgentsRunGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CloudAgentsRunGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.CloudAgentRun>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/cloud_agents/runs/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/cloud-agents/runs/${result.id}`)
    },
})

const CloudAgentsRunListSchema = () => {
    const CloudAgentsRunsListQueryParams = orvalSchemas.CloudAgentsRunsListQueryParams()
    return CloudAgentsRunsListQueryParams
}

const cloudAgentsRunList = (): ToolBase<
    ReturnType<typeof CloudAgentsRunListSchema>,
    WithPostHogUrl<Schemas.PaginatedCloudAgentRunList>
> => ({
    name: 'cloud-agents-run-list',
    schema: CloudAgentsRunListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CloudAgentsRunListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedCloudAgentRunList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/cloud_agents/runs/`,
            query: {
                created_after: params.created_after,
                created_before: params.created_before,
                limit: params.limit,
                offset: params.offset,
                preset_id: params.preset_id,
                repository: params.repository,
                status: params.status,
                tag: params.tag,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'status',
                    'status_reason',
                    'status_detail',
                    'created_at',
                    'ended_at',
                    'prompt',
                    'repositories',
                    'preset',
                    'result.pr_url',
                    'cost.total_usd',
                    'cost.final',
                    'tags',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(
            context,
            {
                ...filtered,
                results: await Promise.all(
                    (filtered.results ?? []).map((item) =>
                        withPostHogUrl(context, item, `/cloud-agents/runs/${item.id}`)
                    )
                ),
            },
            '/cloud-agents'
        )
    },
})

const CloudAgentsRunMessageSchema = () => {
    const CloudAgentsRunsMessagesCreateBody = orvalSchemas.CloudAgentsRunsMessagesCreateBody()
    const CloudAgentsRunsMessagesCreateParams = orvalSchemas.CloudAgentsRunsMessagesCreateParams()
    return CloudAgentsRunsMessagesCreateParams.omit({ project_id: true })
        .extend(CloudAgentsRunsMessagesCreateBody.shape)
        .extend({
            id: CloudAgentsRunsMessagesCreateParams.shape['id'].describe(
                'ID of the run to send the message to (a UUID).'
            ),
        })
}

const cloudAgentsRunMessage = (): ToolBase<ReturnType<typeof CloudAgentsRunMessageSchema>, unknown> => ({
    name: 'cloud-agents-run-message',
    schema: CloudAgentsRunMessageSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CloudAgentsRunMessageSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/cloud_agents/runs/${encodeURIComponent(String(params.id))}/messages/`,
            body,
        })
        const filtered = pickResponseFields(result, [
            'resumed',
            'run.id',
            'run.status',
            'run.status_reason',
            'run.status_detail',
            'run.agent_sessions',
        ]) as typeof result
        return filtered
    },
})

const CloudAgentsRunUsageSchema = () => {
    const CloudAgentsRunsUsageRetrieveParams = orvalSchemas.CloudAgentsRunsUsageRetrieveParams()
    return CloudAgentsRunsUsageRetrieveParams.omit({ project_id: true }).extend({
        id: CloudAgentsRunsUsageRetrieveParams.shape['id'].describe('ID of the run (a UUID).'),
    })
}

const cloudAgentsRunUsage = (): ToolBase<ReturnType<typeof CloudAgentsRunUsageSchema>, Schemas.CloudAgentRunUsage> => ({
    name: 'cloud-agents-run-usage',
    schema: CloudAgentsRunUsageSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CloudAgentsRunUsageSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.CloudAgentRunUsage>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/cloud_agents/runs/${encodeURIComponent(String(params.id))}/usage/`,
        })
        return result
    },
})

const CloudAgentsUsageSummarySchema = () => {
    const CloudAgentsUsageRetrieveQueryParams = orvalSchemas.CloudAgentsUsageRetrieveQueryParams()
    return CloudAgentsUsageRetrieveQueryParams
}

const cloudAgentsUsageSummary = (): ToolBase<
    ReturnType<typeof CloudAgentsUsageSummarySchema>,
    Schemas.CloudAgentUsageSummary
> => ({
    name: 'cloud-agents-usage-summary',
    schema: CloudAgentsUsageSummarySchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CloudAgentsUsageSummarySchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.CloudAgentUsageSummary>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/cloud_agents/usage/`,
            query: {
                date_from: params.date_from,
                date_to: params.date_to,
                group_by: params.group_by,
            },
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'cloud-agents-catalog': cloudAgentsCatalog,
    'cloud-agents-estimate': cloudAgentsEstimate,
    'cloud-agents-preset-create': cloudAgentsPresetCreate,
    'cloud-agents-preset-get': cloudAgentsPresetGet,
    'cloud-agents-preset-list': cloudAgentsPresetList,
    'cloud-agents-run-cancel': cloudAgentsRunCancel,
    'cloud-agents-run-create': cloudAgentsRunCreate,
    'cloud-agents-run-events': cloudAgentsRunEvents,
    'cloud-agents-run-get': cloudAgentsRunGet,
    'cloud-agents-run-list': cloudAgentsRunList,
    'cloud-agents-run-message': cloudAgentsRunMessage,
    'cloud-agents-run-usage': cloudAgentsRunUsage,
    'cloud-agents-usage-summary': cloudAgentsUsageSummary,
}
