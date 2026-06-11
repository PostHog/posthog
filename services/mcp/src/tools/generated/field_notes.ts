// AUTO-GENERATED from products/field_notes/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { FieldNotesListQueryParams, FieldNotesRetrieveParams } from '@/generated/field_notes/api'
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
                host: params.host,
                limit: params.limit,
                note_status: params.note_status,
                offset: params.offset,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'comment',
                    'note_status',
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

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'field-notes-get': fieldNotesGet,
    'field-notes-list': fieldNotesList,
}
