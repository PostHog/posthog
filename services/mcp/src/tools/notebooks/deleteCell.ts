import { z } from 'zod'

import type { Context, ToolBase } from '@/tools/types'

import { directDependents, findCellTag, parseCellTags, removeCellTag } from './cellTags'
import { applyMarkdownEdit, fetchMarkdownNotebook } from './markdownDoc'

export const NotebooksDeleteCellSchema = z
    .object({
        notebook_id: z.string().describe('The notebook short_id (the public id in the URL, e.g. `aBcD1234`).'),
        node_id: z.string().describe('The cell to delete, as returned by notebooks-add-cell.'),
    })
    .strict()

export interface DeleteCellResult {
    deleted: true
    orphaned_dependents: { node_id: string; dataframe_name?: string }[]
}

export const deleteCellHandler: ToolBase<typeof NotebooksDeleteCellSchema, DeleteCellResult>['handler'] = async (
    context: Context,
    params: z.infer<typeof NotebooksDeleteCellSchema>
) => {
    const initial = await fetchMarkdownNotebook(context, params.notebook_id)
    const existing = findCellTag(initial.markdown, params.node_id)
    if (!existing) {
        throw new Error(`No cell with node_id ${params.node_id} in notebook ${params.notebook_id}.`)
    }
    // Computed before the delete: dependents reference the doomed cell's dataframe and will
    // break (or silently run against its last result) until the agent rewrites or removes them.
    const orphaned = existing.returnVariable
        ? directDependents(parseCellTags(initial.markdown), existing.returnVariable, params.node_id)
        : []

    await applyMarkdownEdit(context, params.notebook_id, (markdown) => {
        const block = findCellTag(markdown, params.node_id)
        if (!block) {
            return markdown
        }
        return removeCellTag(markdown, block)
    })

    return { deleted: true, orphaned_dependents: orphaned }
}

const tool = (): ToolBase<typeof NotebooksDeleteCellSchema, DeleteCellResult> => ({
    name: 'notebooks-delete-cell',
    schema: NotebooksDeleteCellSchema,
    handler: deleteCellHandler,
})

export default tool
