// AUTO-GENERATED from products/toolbar_annotations/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    ToolbarAnnotationsListQueryParams,
    ToolbarAnnotationsPartialUpdateBody,
    ToolbarAnnotationsPartialUpdateParams,
    ToolbarAnnotationsRetrieveParams,
} from '@/generated/toolbar_annotations/api'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ToolbarAnnotationsListSchema = ToolbarAnnotationsListQueryParams

const toolbarAnnotationsList = (): ToolBase<
    typeof ToolbarAnnotationsListSchema,
    WithPostHogUrl<Schemas.PaginatedToolbarAnnotationList>
> => ({
    name: 'toolbar-annotations-list',
    schema: ToolbarAnnotationsListSchema,
    handler: async (context: Context, params: z.infer<typeof ToolbarAnnotationsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedToolbarAnnotationList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/toolbar_annotations/`,
            query: {
                annotation_status: params.annotation_status,
                host: params.host,
                limit: params.limit,
                offset: params.offset,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'comment',
                    'annotation_status',
                    'resolution',
                    'url',
                    'host',
                    'pathname',
                    'selector',
                    'element_text',
                    'screenshot_url',
                    'created_at',
                    'created_by',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(
            context,
            {
                ...filtered,
                results: await Promise.all(
                    (filtered.results ?? []).map((item) =>
                        withPostHogUrl(context, item, `/toolbar_annotations/${item.id}`)
                    )
                ),
            },
            '/toolbar_annotations'
        )
    },
})

const ToolbarAnnotationsGetSchema = ToolbarAnnotationsRetrieveParams.omit({ project_id: true })

const toolbarAnnotationsGet = (): ToolBase<
    typeof ToolbarAnnotationsGetSchema,
    WithPostHogUrl<Schemas.ToolbarAnnotation>
> => ({
    name: 'toolbar-annotations-get',
    schema: ToolbarAnnotationsGetSchema,
    handler: async (context: Context, params: z.infer<typeof ToolbarAnnotationsGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ToolbarAnnotation>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/toolbar_annotations/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/toolbar_annotations/${result.id}`)
    },
})

const ToolbarAnnotationsUpdateSchema = ToolbarAnnotationsPartialUpdateParams.omit({ project_id: true })
    .extend(ToolbarAnnotationsPartialUpdateBody.shape)
    .extend({
        annotation_status: ToolbarAnnotationsPartialUpdateBody.shape['annotation_status'].describe(
            "New lifecycle status: 'acknowledged' (picked up), 'resolved' (addressed), or 'dismissed' (won't fix). Leave unset to only update the resolution note."
        ),
        resolution: ToolbarAnnotationsPartialUpdateBody.shape['resolution'].describe(
            'Note describing what was done about the annotation.'
        ),
    })

const toolbarAnnotationsUpdate = (): ToolBase<
    typeof ToolbarAnnotationsUpdateSchema,
    WithPostHogUrl<Schemas.ToolbarAnnotation>
> => ({
    name: 'toolbar-annotations-update',
    schema: ToolbarAnnotationsUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof ToolbarAnnotationsUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.comment !== undefined) {
            body['comment'] = params.comment
        }
        if (params.annotation_status !== undefined) {
            body['annotation_status'] = params.annotation_status
        }
        if (params.resolution !== undefined) {
            body['resolution'] = params.resolution
        }
        if (params.url !== undefined) {
            body['url'] = params.url
        }
        if (params.host !== undefined) {
            body['host'] = params.host
        }
        if (params.pathname !== undefined) {
            body['pathname'] = params.pathname
        }
        if (params.selector !== undefined) {
            body['selector'] = params.selector
        }
        if (params.element_text !== undefined) {
            body['element_text'] = params.element_text
        }
        if (params.element_chain !== undefined) {
            body['element_chain'] = params.element_chain
        }
        if (params.element_context !== undefined) {
            body['element_context'] = params.element_context
        }
        if (params.viewport !== undefined) {
            body['viewport'] = params.viewport
        }
        if (params.screenshot_url !== undefined) {
            body['screenshot_url'] = params.screenshot_url
        }
        const result = await context.api.request<Schemas.ToolbarAnnotation>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/toolbar_annotations/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/toolbar_annotations/${result.id}`)
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'toolbar-annotations-list': toolbarAnnotationsList,
    'toolbar-annotations-get': toolbarAnnotationsGet,
    'toolbar-annotations-update': toolbarAnnotationsUpdate,
}
