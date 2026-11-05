import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import type { WithInformationalResponse } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

import { runCellAndWriteBack, wrapRunResultAsInformational, type RunnableCell, type ShapedRunResult } from './cellRuns'
import { directDependents, findCellTag, parseCellTags } from './cellTags'
import { fetchMarkdownNotebook } from './markdownDoc'
import { NOTEBOOK_SHORT_ID_DESCRIPTION, notebookIdAliases } from './notebookId'

const RunCellInputSchema = z
    .object({
        notebook_id: z.string().describe(NOTEBOOK_SHORT_ID_DESCRIPTION),
        node_id: z
            .string()
            .describe('The SQL or Python cell to run, as returned by notebooks-add-cell or notebooks-get.'),
    })
    .strict()

export const NotebooksRunCellSchema = z.preprocess(notebookIdAliases('notebook_id'), RunCellInputSchema)

export interface RunCellResult {
    node_id: string
    run: ShapedRunResult
    stale_dependents: { node_id: string; dataframe_name?: string }[]
    visualization_warnings?: string[]
}

export async function runExistingCell(
    context: Context,
    notebookId: string,
    cell: RunnableCell,
    markdown: string,
    variables: Schemas.NotebookVariable[] | undefined
): Promise<WithInformationalResponse<RunCellResult>> {
    const cells = parseCellTags(markdown)
    const { run, warnings } = await runCellAndWriteBack(context, notebookId, cell, cells, variables)
    return wrapRunResultAsInformational({
        node_id: cell.nodeId,
        run,
        stale_dependents: run.status === 'done' ? directDependents(cells, cell.returnVariable, cell.nodeId) : [],
        ...(warnings.length ? { visualization_warnings: warnings } : {}),
    })
}

export const runCellHandler: ToolBase<typeof NotebooksRunCellSchema, RunCellResult>['handler'] = async (
    context: Context,
    params: z.infer<typeof NotebooksRunCellSchema>
) => {
    const { notebook, markdown } = await fetchMarkdownNotebook(context, params.notebook_id)
    const cell = findCellTag(markdown, params.node_id)
    if (!cell || (cell.tagName !== 'SQLV2' && cell.tagName !== 'PythonV2')) {
        throw new Error(
            `No SQL or Python cell with node_id ${params.node_id} in notebook ${params.notebook_id}. Only SQL and Python cells run. Read the cell ids with notebooks-get.`
        )
    }
    if (!cell.code.trim()) {
        throw new Error(`Cell ${params.node_id} has no code to run. Set it with notebooks-update-cell.`)
    }
    return await runExistingCell(
        context,
        params.notebook_id,
        { nodeId: params.node_id, tagName: cell.tagName, code: cell.code, returnVariable: cell.returnVariable },
        markdown,
        notebook.variables
    )
}

const tool = (): ToolBase<typeof NotebooksRunCellSchema, RunCellResult> => ({
    name: 'notebooks-run-cell',
    schema: NotebooksRunCellSchema,
    handler: runCellHandler,
})

export default tool
