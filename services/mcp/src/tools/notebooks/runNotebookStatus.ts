import { z } from 'zod'

import type { Context, ToolBase } from '@/tools/types'

import { wrapRunResultAsInformational } from './cellRuns'
import { notebookPathFor } from './markdownDoc'
import { awaitNotebookRun, type NotebookRunOutcome } from './notebookRuns'
import { NOTEBOOK_SHORT_ID_DESCRIPTION, notebookIdAliases } from './notebookId'

const RunNotebookStatusInputSchema = z
    .object({
        notebook_id: z.string().describe(NOTEBOOK_SHORT_ID_DESCRIPTION),
        run_id: z.string().describe('The run to continue waiting on, as returned by notebooks-run.'),
    })
    .strict()

export const NotebooksRunStatusSchema = z.preprocess(notebookIdAliases('notebook_id'), RunNotebookStatusInputSchema)

export const runNotebookStatusHandler: ToolBase<
    typeof NotebooksRunStatusSchema,
    NotebookRunOutcome
>['handler'] = async (context: Context, params: z.infer<typeof NotebooksRunStatusSchema>) => {
    const projectId = await context.stateManager.getProjectId()
    const notebookPath = notebookPathFor(projectId, params.notebook_id)
    // Idempotent: a cell whose result already carries this run's id is not written again, so
    // calling this repeatedly costs polls rather than document versions.
    const outcome = await awaitNotebookRun(context, params.notebook_id, notebookPath, params.run_id)
    return wrapRunResultAsInformational(outcome)
}

const tool = (): ToolBase<typeof NotebooksRunStatusSchema, NotebookRunOutcome> => ({
    name: 'notebooks-run-status',
    schema: NotebooksRunStatusSchema,
    handler: runNotebookStatusHandler,
})

export default tool
