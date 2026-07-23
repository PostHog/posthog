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
import { castStringToInt } from '@/tools/cast-helpers'
import { withPostHogUrl, pickResponseFields, omitResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

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

const CohortsListSchema = CohortsListQueryParams.extend({
    limit: z.preprocess(castStringToInt, CohortsListQueryParams.shape['limit']).optional(),
    offset: z.preprocess(castStringToInt, CohortsListQueryParams.shape['offset']).optional(),
    search: CohortsListQueryParams.shape['search'].describe(
        'Find cohorts by name. Fuzzy trigram match (tolerates typos and partial words), exact matches ordered first.'
    ),
    hide_behavioral_cohorts: CohortsListQueryParams.shape['hide_behavioral_cohorts'].describe(
        'Set true to exclude behavioral (event-based) cohorts — not usable in batch workflow audiences.'
    ),
})

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
                    basic: params.basic,
                    hide_behavioral_cohorts: params.hide_behavioral_cohorts,
                    limit: params.limit,
                    offset: params.offset,
                    search: params.search,
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

const CohortsPartialUpdateSchema = CohortsPartialUpdateParams.omit({ project_id: true })
    .extend(CohortsPartialUpdateBody.omit({ _create_in_folder: true, _create_static_person_ids: true }).shape)
    .extend({ id: z.preprocess(castStringToInt, CohortsPartialUpdateParams.shape['id']) })

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

const CohortsRetrieveSchema = CohortsRetrieveParams.omit({ project_id: true }).extend({
    id: z.preprocess(castStringToInt, CohortsRetrieveParams.shape['id']),
})

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
            const filtered = omitResponseFields(result, [
                'filters.properties.values.*.values.*.bytecode',
                'filters.properties.values.*.values.*.bytecode_error',
                'filters.properties.values.*.values.*.conditionHash',
                'filters.properties.values.*.bytecode',
                'filters.properties.values.*.bytecode_error',
                'filters.properties.values.*.conditionHash',
            ]) as typeof result
            return await withPostHogUrl(context, filtered, `/cohorts/${filtered.id}`)
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
    'cohorts-add-persons-to-static-cohort-partial-update': cohortsAddPersonsToStaticCohortPartialUpdate,
    'cohorts-create': cohortsCreate,
    'cohorts-list': cohortsList,
    'cohorts-partial-update': cohortsPartialUpdate,
    'cohorts-retrieve': cohortsRetrieve,
    'cohorts-rm-person-from-static-cohort-partial-update': cohortsRmPersonFromStaticCohortPartialUpdate,
}
