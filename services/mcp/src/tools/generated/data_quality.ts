// AUTO-GENERATED from products/data_quality/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/data_quality/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const DataQualityCheckCreateSchema = () => {
    const DataQualityChecksCreateBody = orvalSchemas.DataQualityChecksCreateBody()
    return DataQualityChecksCreateBody
}

const dataQualityCheckCreate = (): ToolBase<
    ReturnType<typeof DataQualityCheckCreateSchema>,
    Schemas.DataQualityCheckCreate
> => ({
    name: 'data-quality-check-create',
    schema: DataQualityCheckCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof DataQualityCheckCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.subject_type !== undefined) {
            body['subject_type'] = params.subject_type
        }
        if (params.subject_uuid !== undefined) {
            body['subject_uuid'] = params.subject_uuid
        }
        if (params.column_name !== undefined) {
            body['column_name'] = params.column_name
        }
        if (params.check_type !== undefined) {
            body['check_type'] = params.check_type
        }
        if (params.config !== undefined) {
            body['config'] = params.config
        }
        if (params.severity !== undefined) {
            body['severity'] = params.severity
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.created_source !== undefined) {
            body['created_source'] = params.created_source
        }
        if (params.ai_model !== undefined) {
            body['ai_model'] = params.ai_model
        }
        if (params.confidence !== undefined) {
            body['confidence'] = params.confidence
        }
        if (params.reasoning !== undefined) {
            body['reasoning'] = params.reasoning
        }
        body['created_source'] = 'ai_generated'
        const result = await context.api.request<Schemas.DataQualityCheckCreate>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/data_quality_checks/`,
            body,
        })
        return result
    },
})

const DataQualityCheckDeleteSchema = () => {
    const DataQualityChecksDestroyParams = orvalSchemas.DataQualityChecksDestroyParams()
    return DataQualityChecksDestroyParams.omit({ project_id: true })
}

const dataQualityCheckDelete = (): ToolBase<ReturnType<typeof DataQualityCheckDeleteSchema>, unknown> => ({
    name: 'data-quality-check-delete',
    schema: DataQualityCheckDeleteSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof DataQualityCheckDeleteSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/data_quality_checks/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const DataQualityCheckResultsSchema = () => {
    const DataQualityChecksRunsListParams = orvalSchemas.DataQualityChecksRunsListParams()
    return DataQualityChecksRunsListParams.omit({ project_id: true })
}

const dataQualityCheckResults = (): ToolBase<
    ReturnType<typeof DataQualityCheckResultsSchema>,
    Schemas.DataQualityCheckRun[]
> => ({
    name: 'data-quality-check-results',
    schema: DataQualityCheckResultsSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof DataQualityCheckResultsSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DataQualityCheckRun[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/data_quality_checks/${encodeURIComponent(String(params.id))}/runs/`,
        })
        return result
    },
})

const DataQualityCheckRunSchema = () => {
    const DataQualityChecksRunCreateParams = orvalSchemas.DataQualityChecksRunCreateParams()
    return DataQualityChecksRunCreateParams.omit({ project_id: true })
}

const dataQualityCheckRun = (): ToolBase<
    ReturnType<typeof DataQualityCheckRunSchema>,
    Schemas.DataQualitySuiteRun
> => ({
    name: 'data-quality-check-run',
    schema: DataQualityCheckRunSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof DataQualityCheckRunSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DataQualitySuiteRun>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/data_quality_checks/${encodeURIComponent(String(params.id))}/run/`,
        })
        return result
    },
})

const DataQualityCheckScheduleSchema = () => {
    const DataQualityChecksSchedulePartialUpdateBody = orvalSchemas.DataQualityChecksSchedulePartialUpdateBody()
    return DataQualityChecksSchedulePartialUpdateBody.extend({
        subject_type: DataQualityChecksSchedulePartialUpdateBody.shape['subject_type'].unwrap(),
        subject_uuid: DataQualityChecksSchedulePartialUpdateBody.shape['subject_uuid'].unwrap(),
    })
}

const dataQualityCheckSchedule = (): ToolBase<
    ReturnType<typeof DataQualityCheckScheduleSchema>,
    Schemas.DataQualityCheckSchedule
> => ({
    name: 'data-quality-check-schedule',
    schema: DataQualityCheckScheduleSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof DataQualityCheckScheduleSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.subject_type !== undefined) {
            body['subject_type'] = params.subject_type
        }
        if (params.subject_uuid !== undefined) {
            body['subject_uuid'] = params.subject_uuid
        }
        if (params.interval !== undefined) {
            body['interval'] = params.interval
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        const result = await context.api.request<Schemas.DataQualityCheckSchedule>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/data_quality_checks/schedule/`,
            body,
        })
        return result
    },
})

const DataQualityCheckTypesSchema = () => {
    const DataQualityChecksCheckTypesListQueryParams = orvalSchemas.DataQualityChecksCheckTypesListQueryParams()
    return DataQualityChecksCheckTypesListQueryParams
}

const dataQualityCheckTypes = (): ToolBase<
    ReturnType<typeof DataQualityCheckTypesSchema>,
    Schemas.DataQualityCheckType[]
> => ({
    name: 'data-quality-check-types',
    schema: DataQualityCheckTypesSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof DataQualityCheckTypesSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DataQualityCheckType[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/data_quality_checks/check_types/`,
            query: {
                subject_type: params.subject_type,
            },
        })
        return result
    },
})

const DataQualityCheckUpdateSchema = () => {
    const DataQualityChecksPartialUpdateBody = orvalSchemas.DataQualityChecksPartialUpdateBody()
    const DataQualityChecksPartialUpdateParams = orvalSchemas.DataQualityChecksPartialUpdateParams()
    return DataQualityChecksPartialUpdateParams.omit({ project_id: true }).extend(
        DataQualityChecksPartialUpdateBody.shape
    )
}

const dataQualityCheckUpdate = (): ToolBase<
    ReturnType<typeof DataQualityCheckUpdateSchema>,
    Schemas.DataQualityCheck
> => ({
    name: 'data-quality-check-update',
    schema: DataQualityCheckUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof DataQualityCheckUpdateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.column_name !== undefined) {
            body['column_name'] = params.column_name
        }
        if (params.check_type !== undefined) {
            body['check_type'] = params.check_type
        }
        if (params.config !== undefined) {
            body['config'] = params.config
        }
        if (params.severity !== undefined) {
            body['severity'] = params.severity
        }
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.created_source !== undefined) {
            body['created_source'] = params.created_source
        }
        if (params.ai_model !== undefined) {
            body['ai_model'] = params.ai_model
        }
        if (params.confidence !== undefined) {
            body['confidence'] = params.confidence
        }
        if (params.reasoning !== undefined) {
            body['reasoning'] = params.reasoning
        }
        const result = await context.api.request<Schemas.DataQualityCheck>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/data_quality_checks/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const DataQualitySubjectsSchema = () => z.object({})

const dataQualitySubjects = (): ToolBase<
    ReturnType<typeof DataQualitySubjectsSchema>,
    Schemas.DataQualitySubject[]
> => ({
    name: 'data-quality-subjects',
    schema: DataQualitySubjectsSchema(),
    handler: async (context: Context, _params: z.infer<ReturnType<typeof DataQualitySubjectsSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DataQualitySubject[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/data_quality_checks/subjects/`,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'data-quality-check-create': dataQualityCheckCreate,
    'data-quality-check-delete': dataQualityCheckDelete,
    'data-quality-check-results': dataQualityCheckResults,
    'data-quality-check-run': dataQualityCheckRun,
    'data-quality-check-schedule': dataQualityCheckSchedule,
    'data-quality-check-types': dataQualityCheckTypes,
    'data-quality-check-update': dataQualityCheckUpdate,
    'data-quality-subjects': dataQualitySubjects,
}
