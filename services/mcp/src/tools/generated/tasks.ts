// AUTO-GENERATED from products/tasks/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/tasks/api'
import {
    ChannelInstructionsBaseVersionSchema,
    TaskAgentCreateSchema,
    TaskAgentRunCreateSchema,
} from '@/schema/tool-inputs'
import { withPostHogUrl, pickResponseFields, omitResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ChannelCreateSchema = () => {
    const TaskChannelsCreateBody = orvalSchemas.TaskChannelsCreateBody()
    return TaskChannelsCreateBody
}

const channelCreate = (): ToolBase<ReturnType<typeof ChannelCreateSchema>, Schemas.ChannelDTO> => ({
    name: 'channel-create',
    schema: ChannelCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ChannelCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.channel_type !== undefined) {
            body['channel_type'] = params.channel_type
        }
        if (params.member_ids !== undefined) {
            body['member_ids'] = params.member_ids
        }
        if (params.star !== undefined) {
            body['star'] = params.star
        }
        const result = await context.api.request<Schemas.ChannelDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/task_channels/`,
            body,
        })
        return result
    },
})

const ChannelInstructionsRetrieveSchema = () => {
    const TaskChannelsInstructionsRetrieveParams = orvalSchemas.TaskChannelsInstructionsRetrieveParams()
    return TaskChannelsInstructionsRetrieveParams.omit({ project_id: true }).extend({
        id: TaskChannelsInstructionsRetrieveParams.shape['id'].describe(
            'ID of the channel whose instructions to read.'
        ),
    })
}

const channelInstructionsRetrieve = (): ToolBase<
    ReturnType<typeof ChannelInstructionsRetrieveSchema>,
    Schemas.ChannelInstructionsDTO
> => ({
    name: 'channel-instructions-retrieve',
    schema: ChannelInstructionsRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ChannelInstructionsRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ChannelInstructionsDTO>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/task_channels/${encodeURIComponent(String(params.id))}/instructions/`,
        })
        return result
    },
})

const ChannelInstructionsUpdateSchema = () => {
    const TaskChannelsInstructionsUpdateBody = orvalSchemas.TaskChannelsInstructionsUpdateBody()
    const TaskChannelsInstructionsUpdateParams = orvalSchemas.TaskChannelsInstructionsUpdateParams()
    return TaskChannelsInstructionsUpdateParams.omit({ project_id: true })
        .extend(TaskChannelsInstructionsUpdateBody.shape)
        .extend({
            id: TaskChannelsInstructionsUpdateParams.shape['id'].describe(
                'ID of the channel whose instructions to update.'
            ),
            base_version: ChannelInstructionsBaseVersionSchema,
        })
}

const channelInstructionsUpdate = (): ToolBase<
    ReturnType<typeof ChannelInstructionsUpdateSchema>,
    Schemas.ChannelInstructionsDTO
> => ({
    name: 'channel-instructions-update',
    schema: ChannelInstructionsUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ChannelInstructionsUpdateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        if (params.base_version !== undefined) {
            body['base_version'] = params.base_version
        }
        const result = await context.api.request<Schemas.ChannelInstructionsDTO>({
            method: 'PUT',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/task_channels/${encodeURIComponent(String(params.id))}/instructions/`,
            body,
        })
        return result
    },
})

const ChannelListSchema = () => {
    const TaskChannelsListQueryParams = orvalSchemas.TaskChannelsListQueryParams()
    return TaskChannelsListQueryParams
}

const channelList = (): ToolBase<ReturnType<typeof ChannelListSchema>, Schemas.PaginatedChannelDTOList> => ({
    name: 'channel-list',
    schema: ChannelListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ChannelListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedChannelDTOList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/task_channels/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

const ChannelRetrieveSchema = () => {
    const TaskChannelsRetrieveParams = orvalSchemas.TaskChannelsRetrieveParams()
    return TaskChannelsRetrieveParams.omit({ project_id: true }).extend({
        id: TaskChannelsRetrieveParams.shape['id'].describe('ID of the channel to read.'),
    })
}

const channelRetrieve = (): ToolBase<ReturnType<typeof ChannelRetrieveSchema>, Schemas.ChannelDTO> => ({
    name: 'channel-retrieve',
    schema: ChannelRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ChannelRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ChannelDTO>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/task_channels/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const LoopChannelInstructionsRetrieveSchema = () => {
    const TaskChannelsInstructionsRetrieveParams = orvalSchemas.TaskChannelsInstructionsRetrieveParams()
    return TaskChannelsInstructionsRetrieveParams.omit({ project_id: true }).extend({
        id: TaskChannelsInstructionsRetrieveParams.shape['id'].describe("ID of the loop's context channel."),
    })
}

const loopChannelInstructionsRetrieve = (): ToolBase<
    ReturnType<typeof LoopChannelInstructionsRetrieveSchema>,
    Schemas.ChannelInstructionsDTO
> => ({
    name: 'loop-channel-instructions-retrieve',
    schema: LoopChannelInstructionsRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof LoopChannelInstructionsRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ChannelInstructionsDTO>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/task_channels/${encodeURIComponent(String(params.id))}/instructions/`,
        })
        return result
    },
})

const LoopChannelInstructionsUpdateSchema = () => {
    const TaskChannelsInstructionsUpdateBody = orvalSchemas.TaskChannelsInstructionsUpdateBody()
    const TaskChannelsInstructionsUpdateParams = orvalSchemas.TaskChannelsInstructionsUpdateParams()
    return TaskChannelsInstructionsUpdateParams.omit({ project_id: true })
        .extend(TaskChannelsInstructionsUpdateBody.shape)
        .extend({
            id: TaskChannelsInstructionsUpdateParams.shape['id'].describe("ID of the loop's context channel."),
            base_version: ChannelInstructionsBaseVersionSchema,
        })
}

const loopChannelInstructionsUpdate = (): ToolBase<
    ReturnType<typeof LoopChannelInstructionsUpdateSchema>,
    Schemas.ChannelInstructionsDTO
> => ({
    name: 'loop-channel-instructions-update',
    schema: LoopChannelInstructionsUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof LoopChannelInstructionsUpdateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        if (params.base_version !== undefined) {
            body['base_version'] = params.base_version
        }
        const result = await context.api.request<Schemas.ChannelInstructionsDTO>({
            method: 'PUT',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/task_channels/${encodeURIComponent(String(params.id))}/instructions/`,
            body,
        })
        return result
    },
})

const TasksConfigCreateSchema = () => {
    const TasksConfigCreateBody = orvalSchemas.TasksConfigCreateBody()
    return TasksConfigCreateBody
}

const tasksConfigCreate = (): ToolBase<
    ReturnType<typeof TasksConfigCreateSchema>,
    Schemas.TasksTeamConfigResponse
> => ({
    name: 'tasks-config-create',
    schema: TasksConfigCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof TasksConfigCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.runtime_adapter !== undefined) {
            body['runtime_adapter'] = params.runtime_adapter
        }
        if (params.model !== undefined) {
            body['model'] = params.model
        }
        if (params.reasoning_effort !== undefined) {
            body['reasoning_effort'] = params.reasoning_effort
        }
        const result = await context.api.request<Schemas.TasksTeamConfigResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/config/`,
            body,
        })
        return result
    },
})

const TasksConfigListSchema = () => {
    const TasksConfigListQueryParams = orvalSchemas.TasksConfigListQueryParams()
    return TasksConfigListQueryParams
}

const tasksConfigList = (): ToolBase<ReturnType<typeof TasksConfigListSchema>, Schemas.TasksTeamConfigResponse> => ({
    name: 'tasks-config-list',
    schema: TasksConfigListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof TasksConfigListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.TasksTeamConfigResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/config/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

const TasksCreateSchema = () => {
    const TasksCreateBody = orvalSchemas.TasksCreateBody()
    return TasksCreateBody.omit({
        title_manually_set: true,
        origin_product: true,
        repositories: true,
        github_integration: true,
        github_user_integration: true,
        signal_report: true,
        signal_report_task_relationship: true,
        json_schema: true,
        archived: true,
        ci_prompt: true,
        branch: true,
        runtime_adapter: true,
        model: true,
        reasoning_effort: true,
        initial_permission_mode: true,
        pending_user_message: true,
        pending_user_artifact_ids: true,
        auto_publish: true,
        channel: true,
        start_run: true,
        signal_report_discussion_question: true,
        naming_source: true,
        sandbox_environment_id: true,
        custom_image_id: true,
        runtime: true,
    }).extend({
        description: TasksCreateBody.shape['description']
            .unwrap()
            .describe(
                'The task for the agent to carry out, written as a direct prompt (e.g. "Investigate the spike in $exception events on the checkout page and open a PR with a fix"). Passed verbatim to the agent as its instructions, so be specific.'
            ),
    })
}

const tasksCreate = (): ToolBase<
    ReturnType<typeof TasksCreateSchema>,
    WithPostHogUrl<Schemas.TaskCreateResponseDTO>
> => ({
    name: 'tasks-create',
    schema: TasksCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof TasksCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.title !== undefined) {
            body['title'] = params.title
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.repository !== undefined) {
            body['repository'] = params.repository
        }
        const result = await context.api.request<Schemas.TaskCreateResponseDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/`,
            body,
        })
        const filtered = pickResponseFields(result, [
            'id',
            'task_number',
            'title',
            'description',
            'origin_product',
            'repository',
            'internal',
            'latest_run.id',
            'latest_run.stage',
            'latest_run.status',
            'run_error',
            'created_at',
            'updated_at',
        ]) as typeof result
        return await withPostHogUrl(context, filtered, `/tasks/${filtered.id}`)
    },
})

const TasksCreateAndRunSchema = () => TaskAgentCreateSchema

const tasksCreateAndRun = (): ToolBase<ReturnType<typeof TasksCreateAndRunSchema>, Schemas.TaskCreateResponseDTO> => ({
    name: 'tasks-create-and-run',
    schema: TasksCreateAndRunSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof TasksCreateAndRunSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const parsedParams = TasksCreateAndRunSchema().parse(params)
        const result = await context.api.request<Schemas.TaskCreateResponseDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/`,
            body: parsedParams,
        })
        const filtered = pickResponseFields(result, [
            'id',
            'task_number',
            'title',
            'description',
            'repository',
            'latest_run.id',
            'latest_run.stage',
            'latest_run.status',
            'run_error',
        ]) as typeof result
        return await withPostHogUrl(context, filtered, `/tasks/${filtered.id}`)
    },
})

const TasksListSchema = () => {
    const TasksListQueryParams = orvalSchemas.TasksListQueryParams()
    return TasksListQueryParams
}

const tasksList = (): ToolBase<
    ReturnType<typeof TasksListSchema>,
    WithPostHogUrl<Schemas.PaginatedTaskListItemList>
> => ({
    name: 'tasks-list',
    schema: TasksListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof TasksListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedTaskListItemList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/`,
            query: {
                all_team_tasks: params.all_team_tasks,
                archived: params.archived,
                basic: params.basic,
                channel: params.channel,
                ci_status: params.ci_status,
                client_provenance: params.client_provenance,
                commented_by: params.commented_by,
                created_by: params.created_by,
                exclude_origin_product: params.exclude_origin_product,
                hog_flow_id: params.hog_flow_id,
                internal: params.internal,
                limit: params.limit,
                mentions: params.mentions,
                offset: params.offset,
                ordering: params.ordering,
                organization: params.organization,
                origin_product: params.origin_product,
                pinned: params.pinned,
                pr_state: params.pr_state,
                repository: params.repository,
                search: params.search,
                stage: params.stage,
                status: params.status,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'task_number',
                    'title',
                    'description',
                    'origin_product',
                    'repository',
                    'internal',
                    'channel',
                    'created_by.first_name',
                    'created_by.last_name',
                    'latest_run.id',
                    'latest_run.status',
                    'latest_run.error_message',
                    'latest_run.created_at',
                    'latest_run.completed_at',
                    'created_at',
                    'updated_at',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(
            context,
            {
                ...filtered,
                results: await Promise.all(
                    (filtered.results ?? []).map((item) => withPostHogUrl(context, item, `/tasks/${item.id}`))
                ),
            },
            '/tasks'
        )
    },
})

const TasksMeConfigCreateSchema = () => {
    const TasksMeConfigCreateBody = orvalSchemas.TasksMeConfigCreateBody()
    return TasksMeConfigCreateBody
}

const tasksMeConfigCreate = (): ToolBase<
    ReturnType<typeof TasksMeConfigCreateSchema>,
    Schemas.TasksUserConfigResponse
> => ({
    name: 'tasks-me-config-create',
    schema: TasksMeConfigCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof TasksMeConfigCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.runtime_adapter !== undefined) {
            body['runtime_adapter'] = params.runtime_adapter
        }
        if (params.model !== undefined) {
            body['model'] = params.model
        }
        if (params.reasoning_effort !== undefined) {
            body['reasoning_effort'] = params.reasoning_effort
        }
        const result = await context.api.request<Schemas.TasksUserConfigResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/@me/config/`,
            body,
        })
        return result
    },
})

const TasksMeConfigListSchema = () => {
    const TasksMeConfigListQueryParams = orvalSchemas.TasksMeConfigListQueryParams()
    return TasksMeConfigListQueryParams
}

const tasksMeConfigList = (): ToolBase<
    ReturnType<typeof TasksMeConfigListSchema>,
    Schemas.TasksUserConfigResponse
> => ({
    name: 'tasks-me-config-list',
    schema: TasksMeConfigListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof TasksMeConfigListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.TasksUserConfigResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/@me/config/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

const TasksModelsRetrieveSchema = () => z.object({})

const tasksModelsRetrieve = (): ToolBase<
    ReturnType<typeof TasksModelsRetrieveSchema>,
    Schemas.ModelCatalogueResponse
> => ({
    name: 'tasks-models-retrieve',
    schema: TasksModelsRetrieveSchema(),
    handler: async (context: Context, _params: z.infer<ReturnType<typeof TasksModelsRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ModelCatalogueResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/models/`,
        })
        return result
    },
})

const TasksRetrieveSchema = () => {
    const TasksRetrieveParams = orvalSchemas.TasksRetrieveParams()
    return TasksRetrieveParams.omit({ project_id: true })
}

const tasksRetrieve = (): ToolBase<ReturnType<typeof TasksRetrieveSchema>, WithPostHogUrl<Schemas.TaskDetailDTO>> => ({
    name: 'tasks-retrieve',
    schema: TasksRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof TasksRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.TaskDetailDTO>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/${encodeURIComponent(String(params.id))}/`,
        })
        const filtered = omitResponseFields(result, [
            'latest_run.log_url',
            'latest_run.state.sandbox_connect_token',
            'latest_run.state.sandbox_url',
        ]) as typeof result
        return await withPostHogUrl(context, filtered, `/tasks/${filtered.id}`)
    },
})

const TasksRunCreateSchema = () => TaskAgentRunCreateSchema

const tasksRunCreate = (): ToolBase<ReturnType<typeof TasksRunCreateSchema>, Schemas.TaskRunResponse> => ({
    name: 'tasks-run-create',
    schema: TasksRunCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof TasksRunCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const parsedParams = TasksRunCreateSchema().parse(params)
        const { id, ...body } = parsedParams
        const result = await context.api.request<Schemas.TaskRunResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/${encodeURIComponent(String(id))}/run/`,
            body,
        })
        const filtered = pickResponseFields(result, [
            'run_error',
            'id',
            'task_number',
            'title',
            'description',
            'repository',
            'latest_run.id',
            'latest_run.stage',
            'latest_run.status',
        ]) as typeof result
        return await withPostHogUrl(context, filtered, `/tasks/${filtered.id}`)
    },
})

const TasksRunsListSchema = () => {
    const TasksRunsListParams = orvalSchemas.TasksRunsListParams()
    const TasksRunsListQueryParams = orvalSchemas.TasksRunsListQueryParams()
    return TasksRunsListParams.omit({ project_id: true }).extend(TasksRunsListQueryParams.shape)
}

const tasksRunsList = (): ToolBase<
    ReturnType<typeof TasksRunsListSchema>,
    WithPostHogUrl<Schemas.PaginatedTaskRunDetailDTOList>
> => ({
    name: 'tasks-runs-list',
    schema: TasksRunsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof TasksRunsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedTaskRunDetailDTOList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/${encodeURIComponent(String(params.task_id))}/runs/`,
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
                    'task',
                    'stage',
                    'branch',
                    'status',
                    'environment',
                    'error_message',
                    'state.sandbox_environment_id',
                    'created_at',
                    'updated_at',
                    'completed_at',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/tasks')
    },
})

const TasksRunsRetrieveSchema = () => {
    const TasksRunsRetrieveParams = orvalSchemas.TasksRunsRetrieveParams()
    return TasksRunsRetrieveParams.omit({ project_id: true })
}

const tasksRunsRetrieve = (): ToolBase<ReturnType<typeof TasksRunsRetrieveSchema>, Schemas.TaskRunDetailDTO> => ({
    name: 'tasks-runs-retrieve',
    schema: TasksRunsRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof TasksRunsRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.TaskRunDetailDTO>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/${encodeURIComponent(String(params.task_id))}/runs/${encodeURIComponent(String(params.id))}/`,
        })
        const filtered = omitResponseFields(result, [
            'log_url',
            'state.sandbox_connect_token',
            'state.sandbox_url',
        ]) as typeof result
        return filtered
    },
})

const TasksRunsSessionLogsRetrieveSchema = () => {
    const TasksRunsSessionLogsRetrieveParams = orvalSchemas.TasksRunsSessionLogsRetrieveParams()
    const TasksRunsSessionLogsRetrieveQueryParams = orvalSchemas.TasksRunsSessionLogsRetrieveQueryParams()
    return TasksRunsSessionLogsRetrieveParams.omit({ project_id: true })
        .extend(TasksRunsSessionLogsRetrieveQueryParams.shape)
        .extend({
            limit: TasksRunsSessionLogsRetrieveQueryParams.shape['limit']
                .default(100)
                .optional()
                .describe('Maximum number of entries to return (default 100, max 5000)'),
        })
}

const tasksRunsSessionLogsRetrieve = (): ToolBase<ReturnType<typeof TasksRunsSessionLogsRetrieveSchema>, unknown> => ({
    name: 'tasks-runs-session-logs-retrieve',
    schema: TasksRunsSessionLogsRetrieveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof TasksRunsSessionLogsRetrieveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/tasks/${encodeURIComponent(String(params.task_id))}/runs/${encodeURIComponent(String(params.id))}/session_logs/`,
            query: {
                after: params.after,
                event_types: params.event_types,
                exclude_types: params.exclude_types,
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'channel-create': channelCreate,
    'channel-instructions-retrieve': channelInstructionsRetrieve,
    'channel-instructions-update': channelInstructionsUpdate,
    'channel-list': channelList,
    'channel-retrieve': channelRetrieve,
    'loop-channel-instructions-retrieve': loopChannelInstructionsRetrieve,
    'loop-channel-instructions-update': loopChannelInstructionsUpdate,
    'tasks-config-create': tasksConfigCreate,
    'tasks-config-list': tasksConfigList,
    'tasks-create': tasksCreate,
    'tasks-create-and-run': tasksCreateAndRun,
    'tasks-list': tasksList,
    'tasks-me-config-create': tasksMeConfigCreate,
    'tasks-me-config-list': tasksMeConfigList,
    'tasks-models-retrieve': tasksModelsRetrieve,
    'tasks-retrieve': tasksRetrieve,
    'tasks-run-create': tasksRunCreate,
    'tasks-runs-list': tasksRunsList,
    'tasks-runs-retrieve': tasksRunsRetrieve,
    'tasks-runs-session-logs-retrieve': tasksRunsSessionLogsRetrieve,
}
