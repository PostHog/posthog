import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import type { Context, ToolBase } from '@/tools/types'

import { wrapRunResultAsInformational } from './cellRuns'
import { notebookPathFor } from './markdownDoc'
import { awaitNotebookRun, type NotebookRunOutcome } from './notebookRuns'
import { NOTEBOOK_SHORT_ID_DESCRIPTION, notebookIdAliases } from './notebookId'
import { MAX_NOTEBOOK_VARIABLES, NotebookVariableSchema } from './notebookVariableSchema'

const RunNotebookInputSchema = z
    .object({
        notebook_id: z.string().describe(NOTEBOOK_SHORT_ID_DESCRIPTION),
        variables: z
            .array(NotebookVariableSchema)
            .max(MAX_NOTEBOOK_VARIABLES)
            .optional()
            .describe(
                `Set the notebook's variables before the run, in one call. This replaces the whole list, so include every variable you want to keep, and the notebook stores what you pass. Omit it to run with the variables already saved. At most ${MAX_NOTEBOOK_VARIABLES}.`
            ),
        wait: z
            .boolean()
            .optional()
            .default(true)
            .describe(
                'Wait for the run and write each result into the document as it lands. Set false to start the run and return immediately, then follow with notebooks-run-status.'
            ),
    })
    .strict()

export const NotebooksRunSchema = z.preprocess(notebookIdAliases('notebook_id'), RunNotebookInputSchema)

export const runNotebookHandler: ToolBase<typeof NotebooksRunSchema, NotebookRunOutcome>['handler'] = async (
    context: Context,
    params: z.infer<typeof NotebooksRunSchema>
) => {
    const projectId = await context.stateManager.getProjectId()
    const notebookPath = notebookPathFor(projectId, params.notebook_id)

    const started = await context.api.request<Schemas.NotebookRunStartResponse>({
        method: 'POST',
        path: `${notebookPath}runs/`,
        body: params.variables ? { variables: params.variables } : {},
    })
    const disclosure = {
        starts_sandbox: started.starts_sandbox,
        sandbox_hourly_price: started.sandbox_hourly_price ?? null,
    }

    if (params.wait === false) {
        return wrapRunResultAsInformational({
            run_id: started.run_id,
            status: 'running',
            cell_count: started.cell_count,
            completed_count: 0,
            cells: [],
            ...disclosure,
            hint: 'The notebook is running. Call notebooks-run-status with this run_id to read the results and write them into the document.',
        })
    }

    const outcome = await awaitNotebookRun(context, params.notebook_id, notebookPath, started.run_id)
    return wrapRunResultAsInformational({ ...outcome, ...disclosure })
}

const tool = (): ToolBase<typeof NotebooksRunSchema, NotebookRunOutcome> => ({
    name: 'notebooks-run',
    schema: NotebooksRunSchema,
    handler: runNotebookHandler,
})

export default tool
