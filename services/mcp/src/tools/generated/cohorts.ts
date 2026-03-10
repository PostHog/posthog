// AUTO-GENERATED from products/cohorts/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
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

const cohortsList = (): ToolBase<typeof CohortsListSchema, unknown> => ({
    name: 'cohorts-list',
    schema: CohortsListSchema,
    handler: async (context: Context, params: z.infer<typeof CohortsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedCohortList>({
            method: 'GET',
            path: `/api/projects/${projectId}/cohorts/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        const items = (result as any).results ?? result
        return {
            ...(result as any),
            results: (items as any[]).map((item: any) => ({
                ...item,
                _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/cohorts/${item.id}`,
            })),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/cohorts`,
        }
    },
    _meta: {
        ui: {
            resourceUri: 'ui://posthog/cohort-list.html',
        },
    },
})

const CohortsCreateSchema = CohortsCreateBody.omit({
    groups: true,
    deleted: true,
    _create_in_folder: true,
    _create_static_person_ids: true,
})

const cohortsCreate = (): ToolBase<typeof CohortsCreateSchema, Schemas.Cohort & { _posthogUrl: string }> => ({
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
        const result = await context.api.request<Schemas.Cohort>({
            method: 'POST',
            path: `/api/projects/${projectId}/cohorts/`,
            body,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/cohorts/${(result as any).id}`,
        }
    },
    _meta: {
        ui: {
            resourceUri: 'ui://posthog/cohort.html',
        },
    },
})

const CohortsRetrieveSchema = CohortsRetrieveParams.omit({ project_id: true })

const cohortsRetrieve = (): ToolBase<typeof CohortsRetrieveSchema, Schemas.Cohort & { _posthogUrl: string }> => ({
    name: 'cohorts-retrieve',
    schema: CohortsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof CohortsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Cohort>({
            method: 'GET',
            path: `/api/projects/${projectId}/cohorts/${params.id}/`,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/cohorts/${(result as any).id}`,
        }
    },
    _meta: {
        ui: {
            resourceUri: 'ui://posthog/cohort.html',
        },
    },
})

const CohortsPartialUpdateSchema = CohortsPartialUpdateParams.omit({ project_id: true }).extend(
    CohortsPartialUpdateBody.omit({ groups: true, _create_in_folder: true, _create_static_person_ids: true }).shape
)

const cohortsPartialUpdate = (): ToolBase<
    typeof CohortsPartialUpdateSchema,
    Schemas.Cohort & { _posthogUrl: string }
> => ({
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
        const result = await context.api.request<Schemas.Cohort>({
            method: 'PATCH',
            path: `/api/projects/${projectId}/cohorts/${params.id}/`,
            body,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/cohorts/${(result as any).id}`,
        }
    },
    _meta: {
        ui: {
            resourceUri: 'ui://posthog/cohort.html',
        },
    },
})

const CohortsAddPersonsToStaticCohortPartialUpdateSchema = CohortsAddPersonsToStaticCohortPartialUpdateParams.omit({
    project_id: true,
}).extend(CohortsAddPersonsToStaticCohortPartialUpdateBody.shape)

const cohortsAddPersonsToStaticCohortPartialUpdate = (): ToolBase<
    typeof CohortsAddPersonsToStaticCohortPartialUpdateSchema,
    unknown
> => ({
    name: 'cohorts-add-persons-to-static-cohort-partial-update',
    schema: CohortsAddPersonsToStaticCohortPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof CohortsAddPersonsToStaticCohortPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.person_ids !== undefined) {
            body['person_ids'] = params.person_ids
        }
        const result = await context.api.request<unknown>({
            method: 'PATCH',
            path: `/api/projects/${projectId}/cohorts/${params.id}/add_persons_to_static_cohort/`,
            body,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/cohorts/${(result as any).id}`,
        }
    },
})

const CohortsRmPersonFromStaticCohortPartialUpdateSchema = CohortsRemovePersonFromStaticCohortPartialUpdateParams.omit({
    project_id: true,
}).extend(CohortsRemovePersonFromStaticCohortPartialUpdateBody.shape)

const cohortsRmPersonFromStaticCohortPartialUpdate = (): ToolBase<
    typeof CohortsRmPersonFromStaticCohortPartialUpdateSchema,
    unknown
> => ({
    name: 'cohorts-rm-person-from-static-cohort-partial-update',
    schema: CohortsRmPersonFromStaticCohortPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof CohortsRmPersonFromStaticCohortPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.person_id !== undefined) {
            body['person_id'] = params.person_id
        }
        const result = await context.api.request<unknown>({
            method: 'PATCH',
            path: `/api/projects/${projectId}/cohorts/${params.id}/remove_person_from_static_cohort/`,
            body,
        })
        return {
            ...(result as any),
            _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/cohorts/${(result as any).id}`,
        }
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'cohorts-list': cohortsList,
    'cohorts-create': cohortsCreate,
    'cohorts-retrieve': cohortsRetrieve,
    'cohorts-partial-update': cohortsPartialUpdate,
    'cohorts-add-persons-to-static-cohort-partial-update': cohortsAddPersonsToStaticCohortPartialUpdate,
    'cohorts-rm-person-from-static-cohort-partial-update': cohortsRmPersonFromStaticCohortPartialUpdate,
}
