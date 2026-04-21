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
import { withUiApp } from '@/resources/ui-apps'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const CohortsListSchema = CohortsListQueryParams

const cohortsList = (): ToolBase<typeof CohortsListSchema, WithPostHogUrl<Schemas.PaginatedCohortList>> =>
    withUiApp('cohort-list', {
        name: 'cohorts-list',
        schema: CohortsListSchema,
        handler: async (context: Context, params: z.infer<typeof CohortsListSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.PaginatedCohortList>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/cohorts/`,
                query: {
                    limit: params.limit,
                    offset: params.offset,
                },
            })
            const filtered = {
                ...result,
                results: (result.results ?? []).map((item: any) =>
                    pickResponseFields(item, ['id', 'name', 'description', 'count', 'is_static', 'created_at'])
                ),
            } as typeof result
            return await withPostHogUrl(
                context,
                {
                    ...filtered,
                    results: await Promise.all(
                        (filtered.results ?? []).map((item) => withPostHogUrl(context, item, `/cohorts/${item.id}`))
                    ),
                },
                '/cohorts'
            )
        },
    })

const CohortsCreateSchema = CohortsCreateBody.omit({ _create_in_folder: true, _create_static_person_ids: true })

const cohortsCreate = (): ToolBase<typeof CohortsCreateSchema, WithPostHogUrl<Schemas.Cohort>> =>
    withUiApp('cohort', {
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
                path: `/api/projects/${encodeURIComponent(String(projectId))}/cohorts/`,
                body,
            })
            return await withPostHogUrl(context, result, `/cohorts/${result.id}`)
        },
    })

const CohortsRetrieveSchema = CohortsRetrieveParams.omit({ project_id: true })

const cohortsRetrieve = (): ToolBase<typeof CohortsRetrieveSchema, WithPostHogUrl<Schemas.Cohort>> =>
    withUiApp('cohort', {
        name: 'cohorts-retrieve',
        schema: CohortsRetrieveSchema,
        handler: async (context: Context, params: z.infer<typeof CohortsRetrieveSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.Cohort>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/cohorts/${encodeURIComponent(String(params.id))}/`,
            })
            return await withPostHogUrl(context, result, `/cohorts/${result.id}`)
        },
    })

const CohortsPartialUpdateSchema = CohortsPartialUpdateParams.omit({ project_id: true }).extend(
    CohortsPartialUpdateBody.omit({ _create_in_folder: true, _create_static_person_ids: true }).shape
)

const cohortsPartialUpdate = (): ToolBase<typeof CohortsPartialUpdateSchema, WithPostHogUrl<Schemas.Cohort>> =>
    withUiApp('cohort', {
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
                path: `/api/projects/${encodeURIComponent(String(projectId))}/cohorts/${encodeURIComponent(String(params.id))}/`,
                body,
            })
            return await withPostHogUrl(context, result, `/cohorts/${result.id}`)
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
            path: `/api/projects/${encodeURIComponent(String(projectId))}/cohorts/${encodeURIComponent(String(params.id))}/add_persons_to_static_cohort/`,
            body,
        })
        return result
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
            path: `/api/projects/${encodeURIComponent(String(projectId))}/cohorts/${encodeURIComponent(String(params.id))}/remove_person_from_static_cohort/`,
            body,
        })
        return result
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
