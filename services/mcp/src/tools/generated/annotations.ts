// AUTO-GENERATED from products/annotations/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    AnnotationsCreateBody,
    AnnotationsDestroyParams,
    AnnotationsListQueryParams,
    AnnotationsPartialUpdateBody,
    AnnotationsPartialUpdateParams,
    AnnotationsRetrieveParams,
} from '@/generated/annotations/api'
import { castStringToInt } from '@/tools/cast-helpers'
import { withPostHogUrl, omitResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const AnnotationCreateSchema = AnnotationsCreateBody.omit({
    creation_type: true,
    dashboard_item: true,
    dashboard_id: true,
    deleted: true,
    tags: true,
})

const annotationCreate = (): ToolBase<typeof AnnotationCreateSchema, Schemas.Annotation> => ({
    name: 'annotation-create',
    schema: AnnotationCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AnnotationCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        if (params.date_marker !== undefined) {
            body['date_marker'] = params.date_marker
        }
        if (params.scope !== undefined) {
            body['scope'] = params.scope
        }
        if (params.emoji !== undefined) {
            body['emoji'] = params.emoji
        }
        if (params.hidden_in_user_interface !== undefined) {
            body['hidden_in_user_interface'] = params.hidden_in_user_interface
        }
        const result = await context.api.request<Schemas.Annotation>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/annotations/`,
            body,
        })
        return result
    },
})

const AnnotationDeleteSchema = AnnotationsDestroyParams.omit({ project_id: true })

const annotationDelete = (): ToolBase<typeof AnnotationDeleteSchema, Schemas.Annotation> => ({
    name: 'annotation-delete',
    schema: AnnotationDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof AnnotationDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Annotation>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/annotations/${encodeURIComponent(String(params.id))}/`,
            body: { deleted: true },
        })
        return result
    },
})

const AnnotationRetrieveSchema = AnnotationsRetrieveParams.omit({ project_id: true }).extend({
    id: z.preprocess(castStringToInt, AnnotationsRetrieveParams.shape['id']),
})

const annotationRetrieve = (): ToolBase<typeof AnnotationRetrieveSchema, Schemas.Annotation> => ({
    name: 'annotation-retrieve',
    schema: AnnotationRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof AnnotationRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Annotation>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/annotations/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const AnnotationsListSchema = AnnotationsListQueryParams.extend({
    limit: AnnotationsListQueryParams.shape['limit']
        .default(100)
        .optional()
        .describe('Number of annotations to return per page (default 100).'),
})

const annotationsList = (): ToolBase<
    typeof AnnotationsListSchema,
    WithPostHogUrl<Schemas.PaginatedAnnotationList>
> => ({
    name: 'annotations-list',
    schema: AnnotationsListSchema,
    handler: async (context: Context, params: z.infer<typeof AnnotationsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedAnnotationList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/annotations/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                search: params.search,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                omitResponseFields(item, [
                    'created_by.uuid',
                    'created_by.distinct_id',
                    'created_by.first_name',
                    'created_by.last_name',
                    'created_by.is_email_verified',
                    'created_by.hedgehog_config',
                    'created_by.role_at_organization',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/data-management/annotations')
    },
})

const AnnotationsPartialUpdateSchema = AnnotationsPartialUpdateParams.omit({ project_id: true }).extend(
    AnnotationsPartialUpdateBody.omit({
        creation_type: true,
        dashboard_item: true,
        dashboard_id: true,
        deleted: true,
        tags: true,
    }).shape
)

const annotationsPartialUpdate = (): ToolBase<typeof AnnotationsPartialUpdateSchema, Schemas.Annotation> => ({
    name: 'annotations-partial-update',
    schema: AnnotationsPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof AnnotationsPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.content !== undefined) {
            body['content'] = params.content
        }
        if (params.date_marker !== undefined) {
            body['date_marker'] = params.date_marker
        }
        if (params.scope !== undefined) {
            body['scope'] = params.scope
        }
        if (params.emoji !== undefined) {
            body['emoji'] = params.emoji
        }
        if (params.hidden_in_user_interface !== undefined) {
            body['hidden_in_user_interface'] = params.hidden_in_user_interface
        }
        const result = await context.api.request<Schemas.Annotation>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/annotations/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'annotation-create': annotationCreate,
    'annotation-delete': annotationDelete,
    'annotation-retrieve': annotationRetrieve,
    'annotations-list': annotationsList,
    'annotations-partial-update': annotationsPartialUpdate,
}
