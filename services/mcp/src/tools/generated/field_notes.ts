// AUTO-GENERATED from products/field_notes/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    FieldNotesListQueryParams,
    FieldNotesPartialUpdateBody,
    FieldNotesPartialUpdateParams,
    FieldNotesRetrieveParams,
} from '@/generated/field_notes/api'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const FieldNotesGetSchema = FieldNotesRetrieveParams.omit({ project_id: true })

const fieldNotesGet = (): ToolBase<typeof FieldNotesGetSchema, WithPostHogUrl<Schemas.FieldNote>> => ({
    name: 'field-notes-get',
    schema: FieldNotesGetSchema,
    handler: async (context: Context, params: z.infer<typeof FieldNotesGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.FieldNote>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/field_notes/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/field_notes/${result.id}`)
    },
})

const FieldNotesListSchema = FieldNotesListQueryParams

const fieldNotesList = (): ToolBase<typeof FieldNotesListSchema, WithPostHogUrl<Schemas.PaginatedFieldNoteList>> => ({
    name: 'field-notes-list',
    schema: FieldNotesListSchema,
    handler: async (context: Context, params: z.infer<typeof FieldNotesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedFieldNoteList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/field_notes/`,
            query: {
                field_note_status: params.field_note_status,
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
                    'field_note_status',
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
                    (filtered.results ?? []).map((item) => withPostHogUrl(context, item, `/field_notes/${item.id}`))
                ),
            },
            '/field_notes'
        )
    },
})

const FieldNotesPartialUpdateSchema = FieldNotesPartialUpdateParams.omit({ project_id: true }).extend(
    FieldNotesPartialUpdateBody.shape
)

const fieldNotesPartialUpdate = (): ToolBase<
    typeof FieldNotesPartialUpdateSchema,
    WithPostHogUrl<Schemas.FieldNote>
> => ({
    name: 'field-notes-partial-update',
    schema: FieldNotesPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof FieldNotesPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.comment !== undefined) {
            body['comment'] = params.comment
        }
        if (params.field_note_status !== undefined) {
            body['field_note_status'] = params.field_note_status
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
        const result = await context.api.request<Schemas.FieldNote>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/field_notes/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/field_notes/${result.id}`)
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'field-notes-get': fieldNotesGet,
    'field-notes-list': fieldNotesList,
    'field-notes-partial-update': fieldNotesPartialUpdate,
}
