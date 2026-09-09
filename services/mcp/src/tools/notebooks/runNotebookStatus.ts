import { z } from 'zod'

import type { Context, ToolBase } from '@/tools/types'

import { notebookPathFor } from './markdownDoc'
import { NOTEBOOK_SHORT_ID_DESCRIPTION, notebookIdAliases } from './notebookId'
import { awaitNotebookRun, wrapNotebookRunResult, type NotebookRunResult } from './notebookRuns'

const RunNotebookStatusInputSchema = z
    .object({
        notebook_id: z.string().describe(NOTEBOOK_SHORT_ID_DESCRIPTION),
        run_id: z.string().describe('The run to follow, as returned by notebooks-run.'),
    })
    .strict()

export const NotebooksRunStatusSchema = z.preprocess(notebookIdAliases('notebook_id'), RunNotebookStatusInputSchema)

export const runNotebookStatusHandler: ToolBase<typeof NotebooksRunStatusSchema, NotebookRunResult>['handler'] = async (
    context: Context,
    params: z.infer<typeof NotebooksRunStatusSchema>
) => {
    const projectId = await context.stateManager.getProjectId()
    const notebookPath = notebookPathFor(projectId, params.notebook_id)
    // Idempotent: a cell whose result already sits in the document is written again with the
    // same value, so calling this repeatedly costs one save per poll that saw new results.
    const result = await awaitNotebookRun(context, params.notebook_id, notebookPath, params.run_id)
    return wrapNotebookRunResult(result)
}

const tool = (): ToolBase<typeof NotebooksRunStatusSchema, NotebookRunResult> => ({
    name: 'notebooks-run-status',
    schema: NotebooksRunStatusSchema,
    handler: runNotebookStatusHandler,
})

export default tool
