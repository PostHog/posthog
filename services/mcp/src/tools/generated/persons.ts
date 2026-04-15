// AUTO-GENERATED from products/persons/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    PersonsBulkDeleteCreateBody,
    PersonsCohortsRetrieveQueryParams,
    PersonsDeletePropertyCreateBody,
    PersonsDeletePropertyCreateParams,
    PersonsListQueryParams,
    PersonsRetrieveParams,
    PersonsUpdatePropertyCreateBody,
    PersonsUpdatePropertyCreateParams,
    PersonsValuesRetrieveQueryParams,
} from '@/generated/persons/api'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const PersonsListSchema = PersonsListQueryParams.omit({ format: true, properties: true })

const personsList = (): ToolBase<typeof PersonsListSchema, WithPostHogUrl<Schemas.PaginatedPersonList>> => ({
    name: 'persons-list',
    schema: PersonsListSchema,
    handler: async (context: Context, params: z.infer<typeof PersonsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedPersonList>({
            method: 'GET',
            path: `/api/projects/${projectId}/persons/`,
            query: {
                distinct_id: params.distinct_id,
                email: params.email,
                limit: params.limit,
                offset: params.offset,
                search: params.search,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'uuid',
                    'name',
                    'distinct_ids',
                    'properties.email',
                    'properties.$email',
                    'properties.$geoip_country_code',
                    'created_at',
                    'last_seen_at',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/persons')
    },
})

const PersonsRetrieveSchema = PersonsRetrieveParams.omit({ project_id: true })

const personsRetrieve = (): ToolBase<typeof PersonsRetrieveSchema, WithPostHogUrl<Schemas.Person>> => ({
    name: 'persons-retrieve',
    schema: PersonsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof PersonsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Person>({
            method: 'GET',
            path: `/api/projects/${projectId}/persons/${params.id}/`,
        })
        const filtered = pickResponseFields(result, [
            'id',
            'uuid',
            'name',
            'properties',
            'distinct_ids',
            'created_at',
            'last_seen_at',
        ]) as typeof result
        return await withPostHogUrl(context, filtered, `/persons/${filtered.id}`)
    },
})

const PersonsPropertyDeleteSchema = PersonsDeletePropertyCreateParams.omit({ project_id: true })
    .extend(PersonsDeletePropertyCreateBody.shape)
    .omit({ $unset: true })
    .extend({ unset: PersonsDeletePropertyCreateBody.shape['$unset'] })

const personsPropertyDelete = (): ToolBase<typeof PersonsPropertyDeleteSchema, unknown> => ({
    name: 'persons-property-delete',
    schema: PersonsPropertyDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof PersonsPropertyDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.unset !== undefined) {
            body['$unset'] = params.unset
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${projectId}/persons/${params.id}/delete_property/`,
            body,
        })
        return result
    },
})

const PersonsPropertySetSchema = PersonsUpdatePropertyCreateParams.omit({ project_id: true }).extend(
    PersonsUpdatePropertyCreateBody.shape
)

const personsPropertySet = (): ToolBase<typeof PersonsPropertySetSchema, unknown> => ({
    name: 'persons-property-set',
    schema: PersonsPropertySetSchema,
    handler: async (context: Context, params: z.infer<typeof PersonsPropertySetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.key !== undefined) {
            body['key'] = params.key
        }
        if (params.value !== undefined) {
            body['value'] = params.value
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${projectId}/persons/${params.id}/update_property/`,
            body,
        })
        return result
    },
})

const PersonsBulkDeleteSchema = PersonsBulkDeleteCreateBody

const personsBulkDelete = (): ToolBase<typeof PersonsBulkDeleteSchema, unknown> => ({
    name: 'persons-bulk-delete',
    schema: PersonsBulkDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof PersonsBulkDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.ids !== undefined) {
            body['ids'] = params.ids
        }
        if (params.distinct_ids !== undefined) {
            body['distinct_ids'] = params.distinct_ids
        }
        if (params.delete_events !== undefined) {
            body['delete_events'] = params.delete_events
        }
        if (params.delete_recordings !== undefined) {
            body['delete_recordings'] = params.delete_recordings
        }
        if (params.keep_person !== undefined) {
            body['keep_person'] = params.keep_person
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${projectId}/persons/bulk_delete/`,
            body,
        })
        return result
    },
})

const PersonsCohortsRetrieveSchema = PersonsCohortsRetrieveQueryParams.omit({ format: true })

const personsCohortsRetrieve = (): ToolBase<typeof PersonsCohortsRetrieveSchema, unknown> => ({
    name: 'persons-cohorts-retrieve',
    schema: PersonsCohortsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof PersonsCohortsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${projectId}/persons/cohorts/`,
            query: {
                person_id: params.person_id,
            },
        })
        return result
    },
})

const PersonsValuesRetrieveSchema = PersonsValuesRetrieveQueryParams.omit({ format: true })

const personsValuesRetrieve = (): ToolBase<typeof PersonsValuesRetrieveSchema, unknown> => ({
    name: 'persons-values-retrieve',
    schema: PersonsValuesRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof PersonsValuesRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${projectId}/persons/values/`,
            query: {
                key: params.key,
                value: params.value,
            },
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'persons-list': personsList,
    'persons-retrieve': personsRetrieve,
    'persons-property-delete': personsPropertyDelete,
    'persons-property-set': personsPropertySet,
    'persons-bulk-delete': personsBulkDelete,
    'persons-cohorts-retrieve': personsCohortsRetrieve,
    'persons-values-retrieve': personsValuesRetrieve,
}
