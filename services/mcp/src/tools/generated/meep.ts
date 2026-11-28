// AUTO-GENERATED from products/meep/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/meep/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const MeepTaskStartSchema = () => {
    const MeepTopicsStartTaskBody = orvalSchemas.MeepTopicsStartTaskBody()
    const MeepTopicsStartTaskParams = orvalSchemas.MeepTopicsStartTaskParams()
    return MeepTopicsStartTaskParams.omit({ project_id: true }).extend(MeepTopicsStartTaskBody.shape)
}

const meepTaskStart = (): ToolBase<ReturnType<typeof MeepTaskStartSchema>, Schemas.MeepTaskStartResult> => ({
    name: 'meep-task-start',
    schema: MeepTaskStartSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MeepTaskStartSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.request_id !== undefined) {
            body['request_id'] = params.request_id
        }
        if (params.title !== undefined) {
            body['title'] = params.title
        }
        if (params.brief !== undefined) {
            body['brief'] = params.brief
        }
        const result = await context.api.request<Schemas.MeepTaskStartResult>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/meep/topics/${encodeURIComponent(String(params.id))}/tasks/start/`,
            body,
        })
        return result
    },
})

const MeepTaskWaitSchema = () => {
    const MeepTopicsWaitTasksBody = orvalSchemas.MeepTopicsWaitTasksBody()
    const MeepTopicsWaitTasksParams = orvalSchemas.MeepTopicsWaitTasksParams()
    return MeepTopicsWaitTasksParams.omit({ project_id: true }).extend(MeepTopicsWaitTasksBody.shape)
}

const meepTaskWait = (): ToolBase<ReturnType<typeof MeepTaskWaitSchema>, Schemas.MeepTaskWaitResult> => ({
    name: 'meep-task-wait',
    schema: MeepTaskWaitSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MeepTaskWaitSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.request_id !== undefined) {
            body['request_id'] = params.request_id
        }
        if (params.item_ids !== undefined) {
            body['item_ids'] = params.item_ids
        }
        const result = await context.api.request<Schemas.MeepTaskWaitResult>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/meep/topics/${encodeURIComponent(String(params.id))}/tasks/wait/`,
            body,
        })
        return result
    },
})

const MeepTaskAnswerSchema = () => {
    const MeepTopicsAnswerTaskBody = orvalSchemas.MeepTopicsAnswerTaskBody()
    const MeepTopicsAnswerTaskParams = orvalSchemas.MeepTopicsAnswerTaskParams()
    return MeepTopicsAnswerTaskParams.omit({ project_id: true }).extend(MeepTopicsAnswerTaskBody.shape)
}

const meepTaskAnswer = (): ToolBase<ReturnType<typeof MeepTaskAnswerSchema>, Schemas.MeepTaskStartResult> => ({
    name: 'meep-task-answer',
    schema: MeepTaskAnswerSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MeepTaskAnswerSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.request_id !== undefined) {
            body['request_id'] = params.request_id
        }
        if (params.item_id !== undefined) {
            body['item_id'] = params.item_id
        }
        if (params.question_run_id !== undefined) {
            body['question_run_id'] = params.question_run_id
        }
        if (params.answer !== undefined) {
            body['answer'] = params.answer
        }
        const result = await context.api.request<Schemas.MeepTaskStartResult>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/meep/topics/${encodeURIComponent(String(params.id))}/tasks/answer/`,
            body,
        })
        return result
    },
})

const MeepTopicListSchema = () => {
    const MeepTopicsListQueryParams = orvalSchemas.MeepTopicsListQueryParams()
    return MeepTopicsListQueryParams
}

const meepTopicList = (): ToolBase<ReturnType<typeof MeepTopicListSchema>, Schemas.PaginatedMeepTopicList> => ({
    name: 'meep-topic-list',
    schema: MeepTopicListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MeepTopicListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedMeepTopicList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/meep/topics/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

const MeepTopicGetSchema = () => {
    const MeepTopicsRetrieveParams = orvalSchemas.MeepTopicsRetrieveParams()
    return MeepTopicsRetrieveParams.omit({ project_id: true })
}

const meepTopicGet = (): ToolBase<ReturnType<typeof MeepTopicGetSchema>, Schemas.MeepTopicDetails> => ({
    name: 'meep-topic-get',
    schema: MeepTopicGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MeepTopicGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.MeepTopicDetails>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/meep/topics/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const MeepScoutCreateSchema = () => {
    const MeepTopicsCreateScoutBody = orvalSchemas.MeepTopicsCreateScoutBody()
    const MeepTopicsCreateScoutParams = orvalSchemas.MeepTopicsCreateScoutParams()
    return MeepTopicsCreateScoutParams.omit({ project_id: true }).extend(MeepTopicsCreateScoutBody.shape)
}

const meepScoutCreate = (): ToolBase<ReturnType<typeof MeepScoutCreateSchema>, Schemas.MeepScout> => ({
    name: 'meep-scout-create',
    schema: MeepScoutCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MeepScoutCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.instructions !== undefined) {
            body['instructions'] = params.instructions
        }
        if (params.cron !== undefined) {
            body['cron'] = params.cron
        }
        const result = await context.api.request<Schemas.MeepScout>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/meep/topics/${encodeURIComponent(String(params.id))}/scouts/`,
            body,
        })
        return result
    },
})

const MeepScoutSetEnabledSchema = () => {
    const MeepTopicsSetScoutEnabledBody = orvalSchemas.MeepTopicsSetScoutEnabledBody()
    const MeepTopicsSetScoutEnabledParams = orvalSchemas.MeepTopicsSetScoutEnabledParams()
    return MeepTopicsSetScoutEnabledParams.omit({ project_id: true }).extend(MeepTopicsSetScoutEnabledBody.shape)
}

const meepScoutSetEnabled = (): ToolBase<ReturnType<typeof MeepScoutSetEnabledSchema>, Schemas.MeepScout> => ({
    name: 'meep-scout-set-enabled',
    schema: MeepScoutSetEnabledSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MeepScoutSetEnabledSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.scout_id !== undefined) {
            body['scout_id'] = params.scout_id
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        const result = await context.api.request<Schemas.MeepScout>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/meep/topics/${encodeURIComponent(String(params.id))}/scout_status/`,
            body,
        })
        return result
    },
})

const MeepRoutineBindSchema = () => {
    const MeepTopicsBindRoutineBody = orvalSchemas.MeepTopicsBindRoutineBody()
    const MeepTopicsBindRoutineParams = orvalSchemas.MeepTopicsBindRoutineParams()
    return MeepTopicsBindRoutineParams.omit({ project_id: true }).extend(MeepTopicsBindRoutineBody.shape)
}

const meepRoutineBind = (): ToolBase<ReturnType<typeof MeepRoutineBindSchema>, Schemas.MeepRoutine> => ({
    name: 'meep-routine-bind',
    schema: MeepRoutineBindSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MeepRoutineBindSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.workflow_id !== undefined) {
            body['workflow_id'] = params.workflow_id
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.trigger !== undefined) {
            body['trigger'] = params.trigger
        }
        const result = await context.api.request<Schemas.MeepRoutine>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/meep/topics/${encodeURIComponent(String(params.id))}/routines/`,
            body,
        })
        return result
    },
})

const MeepTopicAddContextSchema = () => {
    const MeepTopicsAddContextBody = orvalSchemas.MeepTopicsAddContextBody()
    const MeepTopicsAddContextParams = orvalSchemas.MeepTopicsAddContextParams()
    return MeepTopicsAddContextParams.omit({ project_id: true }).extend(MeepTopicsAddContextBody.shape)
}

const meepTopicAddContext = (): ToolBase<ReturnType<typeof MeepTopicAddContextSchema>, Schemas.MeepContext> => ({
    name: 'meep-topic-add-context',
    schema: MeepTopicAddContextSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MeepTopicAddContextSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.kind !== undefined) {
            body['kind'] = params.kind
        }
        if (params.text !== undefined) {
            body['text'] = params.text
        }
        if (params.current !== undefined) {
            body['current'] = params.current
        }
        if (params.target !== undefined) {
            body['target'] = params.target
        }
        if (params.unit !== undefined) {
            body['unit'] = params.unit
        }
        if (params.effect !== undefined) {
            body['effect'] = params.effect
        }
        if (params.action !== undefined) {
            body['action'] = params.action
        }
        const result = await context.api.request<Schemas.MeepContext>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/meep/topics/${encodeURIComponent(String(params.id))}/context/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'meep-task-start': meepTaskStart,
    'meep-task-wait': meepTaskWait,
    'meep-task-answer': meepTaskAnswer,
    'meep-topic-list': meepTopicList,
    'meep-topic-get': meepTopicGet,
    'meep-scout-create': meepScoutCreate,
    'meep-scout-set-enabled': meepScoutSetEnabled,
    'meep-routine-bind': meepRoutineBind,
    'meep-topic-add-context': meepTopicAddContext,
}
