// AUTO-GENERATED from definitions/cohorts.yaml + OpenAPI — do not edit
import { z } from 'zod'

import {
    CohortsAddPersonsToStaticCohortPartialUpdateBody,
    CohortsAddPersonsToStaticCohortPartialUpdateParams,
    CohortsCreateBody,
    CohortsListQueryParams,
    CohortsPartialUpdateBody,
    CohortsPartialUpdateParams,
    CohortsRemovePersonFromStaticCohortPartialUpdateBody,
    CohortsRemovePersonFromStaticCohortPartialUpdateParams,
    CohortsRetrieveParams,
} from '@/generated/cohorts/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const CohortsListSchema = CohortsListQueryParams

const cohortsList = (): ToolBase<typeof CohortsListSchema> => ({
    name: 'cohorts-list',
    schema: CohortsListSchema,
    handler: async (context: Context, params: z.infer<typeof CohortsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request({
            method: 'GET',
            path: `/api/projects/${projectId}/cohorts/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        const items = (result as any).results ?? result
        return (items as any[]).map((item: any) => ({
            ...item,
            url: `${context.api.getProjectBaseUrl(projectId)}/cohorts/${item.id}`,
        }))
    },
})

const CohortsCreateSchema = CohortsCreateBody.omit({
    groups: true,
    deleted: true,
    _create_in_folder: true,
    _create_static_person_ids: true,
})

const cohortsCreate = (): ToolBase<typeof CohortsCreateSchema> => ({
    name: 'cohorts-create',
    schema: CohortsCreateSchema,
    handler: async (context: Context, params: z.infer<typeof CohortsCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        if (params.is_static !== undefined) {
            body['is_static'] = params.is_static
        }
        if (params.cohort_type !== undefined) {
            body['cohort_type'] = params.cohort_type
        }
        const result = await context.api.request({
            method: 'POST',
            path: `/api/projects/${projectId}/cohorts/`,
            body,
        })
        return {
            ...(result as any),
            url: `${context.api.getProjectBaseUrl(projectId)}/cohorts/${(result as any).id}`,
        }
    },
})

const CohortsRetrieveSchema = CohortsRetrieveParams.omit({ project_id: true })

const cohortsRetrieve = (): ToolBase<typeof CohortsRetrieveSchema> => ({
    name: 'cohorts-retrieve',
    schema: CohortsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof CohortsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request({
            method: 'GET',
            path: `/api/projects/${projectId}/cohorts/${params.id}/`,
        })
        return {
            ...(result as any),
            url: `${context.api.getProjectBaseUrl(projectId)}/cohorts/${(result as any).id}`,
        }
    },
})

const CohortsPartialUpdateSchema = CohortsPartialUpdateParams.omit({ project_id: true }).merge(
    CohortsPartialUpdateBody.omit({ groups: true, _create_in_folder: true, _create_static_person_ids: true })
)

const cohortsPartialUpdate = (): ToolBase<typeof CohortsPartialUpdateSchema> => ({
    name: 'cohorts-partial-update',
    schema: CohortsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof CohortsPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.query !== undefined) {
            body['query'] = params.query
        }
        if (params.is_static !== undefined) {
            body['is_static'] = params.is_static
        }
        if (params.cohort_type !== undefined) {
            body['cohort_type'] = params.cohort_type
        }
        const result = await context.api.request({
            method: 'PATCH',
            path: `/api/projects/${projectId}/cohorts/${params.id}/`,
            body,
        })
        return {
            ...(result as any),
            url: `${context.api.getProjectBaseUrl(projectId)}/cohorts/${(result as any).id}`,
        }
    },
})

const CohortsAddPersonsToStaticCohortPartialUpdateSchema = CohortsAddPersonsToStaticCohortPartialUpdateParams.omit({
    project_id: true,
}).merge(CohortsAddPersonsToStaticCohortPartialUpdateBody)

const cohortsAddPersonsToStaticCohortPartialUpdate = (): ToolBase<
    typeof CohortsAddPersonsToStaticCohortPartialUpdateSchema
> => ({
    name: 'cohorts-add-persons-to-static-cohort-partial-update',
    schema: CohortsAddPersonsToStaticCohortPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof CohortsAddPersonsToStaticCohortPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.person_ids !== undefined) {
            body['person_ids'] = params.person_ids
        }
        const result = await context.api.request({
            method: 'PATCH',
            path: `/api/projects/${projectId}/cohorts/${params.id}/add_persons_to_static_cohort/`,
            body,
        })
        return {
            ...(result as any),
            url: `${context.api.getProjectBaseUrl(projectId)}/cohorts/${(result as any).id}`,
        }
    },
})

const CohortsRemovePersonFromStaticCohortPartialUpdateSchema =
    CohortsRemovePersonFromStaticCohortPartialUpdateParams.omit({ project_id: true }).merge(
        CohortsRemovePersonFromStaticCohortPartialUpdateBody
    )

const cohortsRemovePersonFromStaticCohortPartialUpdate = (): ToolBase<
    typeof CohortsRemovePersonFromStaticCohortPartialUpdateSchema
> => ({
    name: 'cohorts-remove-person-from-static-cohort-partial-update',
    schema: CohortsRemovePersonFromStaticCohortPartialUpdateSchema,
    handler: async (
        context: Context,
        params: z.infer<typeof CohortsRemovePersonFromStaticCohortPartialUpdateSchema>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.person_id !== undefined) {
            body['person_id'] = params.person_id
        }
        const result = await context.api.request({
            method: 'PATCH',
            path: `/api/projects/${projectId}/cohorts/${params.id}/remove_person_from_static_cohort/`,
            body,
        })
        return {
            ...(result as any),
            url: `${context.api.getProjectBaseUrl(projectId)}/cohorts/${(result as any).id}`,
        }
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'cohorts-list': cohortsList,
    'cohorts-create': cohortsCreate,
    'cohorts-retrieve': cohortsRetrieve,
    'cohorts-partial-update': cohortsPartialUpdate,
    'cohorts-add-persons-to-static-cohort-partial-update': cohortsAddPersonsToStaticCohortPartialUpdate,
    'cohorts-remove-person-from-static-cohort-partial-update': cohortsRemovePersonFromStaticCohortPartialUpdate,
}
