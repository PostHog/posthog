// AUTO-GENERATED from products/hogs/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/hogs/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const HogSaySchema = () => {
    const HogsSayCreateBody = orvalSchemas.HogsSayCreateBody()
    const HogsSayCreateParams = orvalSchemas.HogsSayCreateParams()
    return HogsSayCreateParams.omit({ project_id: true }).extend(HogsSayCreateBody.shape)
}

const hogSay = (): ToolBase<ReturnType<typeof HogSaySchema>, Schemas.HogMessageDTO> => ({
    name: 'hog-say',
    schema: HogSaySchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof HogSaySchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        const result = await context.api.request<Schemas.HogMessageDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hogs/${encodeURIComponent(String(params.id))}/say/`,
            body,
        })
        return result
    },
})

const HogTellSchema = () => {
    const HogsTellCreateBody = orvalSchemas.HogsTellCreateBody()
    const HogsTellCreateParams = orvalSchemas.HogsTellCreateParams()
    return HogsTellCreateParams.omit({ project_id: true }).extend(HogsTellCreateBody.shape)
}

const hogTell = (): ToolBase<ReturnType<typeof HogTellSchema>, Schemas.HogMessageDTO> => ({
    name: 'hog-tell',
    schema: HogTellSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof HogTellSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.to_hog_id !== undefined) {
            body['to_hog_id'] = params.to_hog_id
        }
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        const result = await context.api.request<Schemas.HogMessageDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hogs/${encodeURIComponent(String(params.id))}/tell/`,
            body,
        })
        return result
    },
})

const HogDoneSchema = () => {
    const HogsDoneCreateParams = orvalSchemas.HogsDoneCreateParams()
    return HogsDoneCreateParams.omit({ project_id: true })
}

const hogDone = (): ToolBase<ReturnType<typeof HogDoneSchema>, Schemas.HogDTO> => ({
    name: 'hog-done',
    schema: HogDoneSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof HogDoneSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HogDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hogs/${encodeURIComponent(String(params.id))}/done/`,
        })
        return result
    },
})

const HogUpdateSchema = () => {
    const HogsPartialUpdateBody = orvalSchemas.HogsPartialUpdateBody()
    const HogsPartialUpdateParams = orvalSchemas.HogsPartialUpdateParams()
    return HogsPartialUpdateParams.omit({ project_id: true }).extend(HogsPartialUpdateBody.shape)
}

const hogUpdate = (): ToolBase<ReturnType<typeof HogUpdateSchema>, Schemas.HogDTO> => ({
    name: 'hog-update',
    schema: HogUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof HogUpdateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.emoji !== undefined) {
            body['emoji'] = params.emoji
        }
        if (params.color !== undefined) {
            body['color'] = params.color
        }
        if (params.responsibility !== undefined) {
            body['responsibility'] = params.responsibility
        }
        if (params.memory !== undefined) {
            body['memory'] = params.memory
        }
        if (params.status !== undefined) {
            body['status'] = params.status
        }
        const result = await context.api.request<Schemas.HogDTO>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hogs/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const HogsListSchema = () => z.object({})

const hogsList = (): ToolBase<ReturnType<typeof HogsListSchema>, Schemas.HogDTO[]> => ({
    name: 'hogs-list',
    schema: HogsListSchema(),
    handler: async (context: Context, _params: z.infer<ReturnType<typeof HogsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HogDTO[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hogs/`,
        })
        return result
    },
})

const HogScheduleCreateSchema = () => {
    const HogsSchedulesCreateCreateBody = orvalSchemas.HogsSchedulesCreateCreateBody()
    const HogsSchedulesCreateCreateParams = orvalSchemas.HogsSchedulesCreateCreateParams()
    return HogsSchedulesCreateCreateParams.omit({ project_id: true }).extend(HogsSchedulesCreateCreateBody.shape)
}

const hogScheduleCreate = (): ToolBase<ReturnType<typeof HogScheduleCreateSchema>, Schemas.HogScheduleDTO> => ({
    name: 'hog-schedule-create',
    schema: HogScheduleCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof HogScheduleCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.prompt !== undefined) {
            body['prompt'] = params.prompt
        }
        if (params.run_at !== undefined) {
            body['run_at'] = params.run_at
        }
        if (params.cron_expression !== undefined) {
            body['cron_expression'] = params.cron_expression
        }
        const result = await context.api.request<Schemas.HogScheduleDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hogs/${encodeURIComponent(String(params.id))}/schedules/create/`,
            body,
        })
        return result
    },
})

const HogSchedulesListSchema = () => {
    const HogsSchedulesRetrieveParams = orvalSchemas.HogsSchedulesRetrieveParams()
    return HogsSchedulesRetrieveParams.omit({ project_id: true })
}

const hogSchedulesList = (): ToolBase<ReturnType<typeof HogSchedulesListSchema>, Schemas.HogScheduleDTO[]> => ({
    name: 'hog-schedules-list',
    schema: HogSchedulesListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof HogSchedulesListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HogScheduleDTO[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hogs/${encodeURIComponent(String(params.id))}/schedules/`,
        })
        return result
    },
})

const HogScheduleDeleteSchema = () => {
    const HogsSchedulesDeleteCreateBody = orvalSchemas.HogsSchedulesDeleteCreateBody()
    const HogsSchedulesDeleteCreateParams = orvalSchemas.HogsSchedulesDeleteCreateParams()
    return HogsSchedulesDeleteCreateParams.omit({ project_id: true }).extend(HogsSchedulesDeleteCreateBody.shape)
}

const hogScheduleDelete = (): ToolBase<ReturnType<typeof HogScheduleDeleteSchema>, unknown> => ({
    name: 'hog-schedule-delete',
    schema: HogScheduleDeleteSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof HogScheduleDeleteSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.schedule_id !== undefined) {
            body['schedule_id'] = params.schedule_id
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hogs/${encodeURIComponent(String(params.id))}/schedules/delete/`,
            body,
        })
        return result
    },
})

const HogReportSchema = () => {
    const HogsReportsCreateCreateBody = orvalSchemas.HogsReportsCreateCreateBody()
    const HogsReportsCreateCreateParams = orvalSchemas.HogsReportsCreateCreateParams()
    return HogsReportsCreateCreateParams.omit({ project_id: true }).extend(HogsReportsCreateCreateBody.shape)
}

const hogReport = (): ToolBase<ReturnType<typeof HogReportSchema>, Schemas.HogReportDTO> => ({
    name: 'hog-report',
    schema: HogReportSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof HogReportSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.title !== undefined) {
            body['title'] = params.title
        }
        if (params.summary !== undefined) {
            body['summary'] = params.summary
        }
        if (params.priority !== undefined) {
            body['priority'] = params.priority
        }
        if (params.impact !== undefined) {
            body['impact'] = params.impact
        }
        if (params.proposal !== undefined) {
            body['proposal'] = params.proposal
        }
        if (params.evidence !== undefined) {
            body['evidence'] = params.evidence
        }
        const result = await context.api.request<Schemas.HogReportDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hogs/${encodeURIComponent(String(params.id))}/reports/create/`,
            body,
        })
        return result
    },
})

const HogReportsListSchema = () => {
    const HogsReportsRetrieveParams = orvalSchemas.HogsReportsRetrieveParams()
    return HogsReportsRetrieveParams.omit({ project_id: true })
}

const hogReportsList = (): ToolBase<ReturnType<typeof HogReportsListSchema>, Schemas.HogReportDTO[]> => ({
    name: 'hog-reports-list',
    schema: HogReportsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof HogReportsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HogReportDTO[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hogs/${encodeURIComponent(String(params.id))}/reports/`,
        })
        return result
    },
})

const HogProposeActionSchema = () => {
    const HogsActionsProposeCreateBody = orvalSchemas.HogsActionsProposeCreateBody()
    const HogsActionsProposeCreateParams = orvalSchemas.HogsActionsProposeCreateParams()
    return HogsActionsProposeCreateParams.omit({ project_id: true }).extend(HogsActionsProposeCreateBody.shape)
}

const hogProposeAction = (): ToolBase<ReturnType<typeof HogProposeActionSchema>, Schemas.HogActionDTO> => ({
    name: 'hog-propose-action',
    schema: HogProposeActionSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof HogProposeActionSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.kind !== undefined) {
            body['kind'] = params.kind
        }
        if (params.label !== undefined) {
            body['label'] = params.label
        }
        if (params.draft !== undefined) {
            body['draft'] = params.draft
        }
        const result = await context.api.request<Schemas.HogActionDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hogs/${encodeURIComponent(String(params.id))}/actions/propose/`,
            body,
        })
        return result
    },
})

const HogActionDoneSchema = () => {
    const HogsActionsDoneCreateBody = orvalSchemas.HogsActionsDoneCreateBody()
    const HogsActionsDoneCreateParams = orvalSchemas.HogsActionsDoneCreateParams()
    return HogsActionsDoneCreateParams.omit({ project_id: true }).extend(HogsActionsDoneCreateBody.shape)
}

const hogActionDone = (): ToolBase<ReturnType<typeof HogActionDoneSchema>, Schemas.HogActionDTO> => ({
    name: 'hog-action-done',
    schema: HogActionDoneSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof HogActionDoneSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.action_id !== undefined) {
            body['action_id'] = params.action_id
        }
        if (params.result !== undefined) {
            body['result'] = params.result
        }
        const result = await context.api.request<Schemas.HogActionDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hogs/${encodeURIComponent(String(params.id))}/actions/done/`,
            body,
        })
        return result
    },
})

const HogActionsListSchema = () => {
    const HogsActionsRetrieveParams = orvalSchemas.HogsActionsRetrieveParams()
    return HogsActionsRetrieveParams.omit({ project_id: true })
}

const hogActionsList = (): ToolBase<ReturnType<typeof HogActionsListSchema>, Schemas.HogActionDTO[]> => ({
    name: 'hog-actions-list',
    schema: HogActionsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof HogActionsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HogActionDTO[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hogs/${encodeURIComponent(String(params.id))}/actions/`,
        })
        return result
    },
})

const HogTriggerCreateSchema = () => {
    const HogsTriggersCreateCreateBody = orvalSchemas.HogsTriggersCreateCreateBody()
    const HogsTriggersCreateCreateParams = orvalSchemas.HogsTriggersCreateCreateParams()
    return HogsTriggersCreateCreateParams.omit({ project_id: true }).extend(HogsTriggersCreateCreateBody.shape)
}

const hogTriggerCreate = (): ToolBase<ReturnType<typeof HogTriggerCreateSchema>, Schemas.HogTriggerDTO> => ({
    name: 'hog-trigger-create',
    schema: HogTriggerCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof HogTriggerCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.instructions !== undefined) {
            body['instructions'] = params.instructions
        }
        const result = await context.api.request<Schemas.HogTriggerDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hogs/${encodeURIComponent(String(params.id))}/triggers/create/`,
            body,
        })
        return result
    },
})

const HogTriggersListSchema = () => {
    const HogsTriggersRetrieveParams = orvalSchemas.HogsTriggersRetrieveParams()
    return HogsTriggersRetrieveParams.omit({ project_id: true })
}

const hogTriggersList = (): ToolBase<ReturnType<typeof HogTriggersListSchema>, Schemas.HogTriggerDTO[]> => ({
    name: 'hog-triggers-list',
    schema: HogTriggersListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof HogTriggersListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.HogTriggerDTO[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hogs/${encodeURIComponent(String(params.id))}/triggers/`,
        })
        return result
    },
})

const HogTriggerDeleteSchema = () => {
    const HogsTriggersDeleteCreateBody = orvalSchemas.HogsTriggersDeleteCreateBody()
    const HogsTriggersDeleteCreateParams = orvalSchemas.HogsTriggersDeleteCreateParams()
    return HogsTriggersDeleteCreateParams.omit({ project_id: true }).extend(HogsTriggersDeleteCreateBody.shape)
}

const hogTriggerDelete = (): ToolBase<ReturnType<typeof HogTriggerDeleteSchema>, unknown> => ({
    name: 'hog-trigger-delete',
    schema: HogTriggerDeleteSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof HogTriggerDeleteSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.trigger_id !== undefined) {
            body['trigger_id'] = params.trigger_id
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hogs/${encodeURIComponent(String(params.id))}/triggers/delete/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'hog-say': hogSay,
    'hog-tell': hogTell,
    'hog-done': hogDone,
    'hog-update': hogUpdate,
    'hogs-list': hogsList,
    'hog-schedule-create': hogScheduleCreate,
    'hog-schedules-list': hogSchedulesList,
    'hog-schedule-delete': hogScheduleDelete,
    'hog-report': hogReport,
    'hog-reports-list': hogReportsList,
    'hog-propose-action': hogProposeAction,
    'hog-action-done': hogActionDone,
    'hog-actions-list': hogActionsList,
    'hog-trigger-create': hogTriggerCreate,
    'hog-triggers-list': hogTriggersList,
    'hog-trigger-delete': hogTriggerDelete,
}
