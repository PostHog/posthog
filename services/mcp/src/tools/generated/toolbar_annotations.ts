// AUTO-GENERATED from products/toolbar_annotations/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    ToolbarAnnotationsListQueryParams,
    ToolbarAnnotationsRetrieveParams,
} from '@/generated/toolbar_annotations/api'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

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

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'toolbar-annotations-get': toolbarAnnotationsGet,
    'toolbar-annotations-list': toolbarAnnotationsList,
}
