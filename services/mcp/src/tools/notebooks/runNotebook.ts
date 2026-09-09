import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import type { Context, ToolBase } from '@/tools/types'

import { fetchMarkdownNotebook, notebookPathFor } from './markdownDoc'
import { NOTEBOOK_SHORT_ID_DESCRIPTION, notebookIdAliases } from './notebookId'
import { awaitNotebookRun, wrapNotebookRunResult, type NotebookRunResult } from './notebookRuns'
import { MAX_NOTEBOOK_VARIABLES, NotebookVariableSchema, duplicateVariableNames } from './variables'

const RunNotebookInputSchema = z
    .object({
        notebook_id: z.string().describe(NOTEBOOK_SHORT_ID_DESCRIPTION),
        variables: z
            .array(NotebookVariableSchema)
            .max(MAX_NOTEBOOK_VARIABLES)
            .optional()
            .describe(
                `Save these variables on the notebook before the run starts, so the document and the results agree. This replaces the whole list, so include every variable you want to keep. Omit it to run with the variables already saved. At most ${MAX_NOTEBOOK_VARIABLES}.`
            ),
        wait: z
            .boolean()
            .optional()
            .default(true)
            .describe(
                'Wait up to ~45s for the run to finish before returning. Pass false to return as soon as the run starts, then follow with notebooks-run-status.'
            ),
    })
    .strict()

export const NotebooksRunSchema = z.preprocess(notebookIdAliases('notebook_id'), RunNotebookInputSchema)

export const runNotebookHandler: ToolBase<typeof NotebooksRunSchema, NotebookRunResult>['handler'] = async (
    context: Context,
    params: z.infer<typeof NotebooksRunSchema>
) => {
    if (params.variables) {
        const duplicates = duplicateVariableNames(params.variables)
        if (duplicates.length) {
            throw new Error(`Variable names must be unique. Repeated: ${duplicates.join(', ')}.`)
        }
    }

    // Reading the notebook first is what turns "not a markdown notebook" into a sentence the
    // agent can act on, rather than a 404 from the run endpoint.
    await fetchMarkdownNotebook(context, params.notebook_id)
    const projectId = await context.stateManager.getProjectId()
    const notebookPath = notebookPathFor(projectId, params.notebook_id)

    const started = await context.api.request<Schemas.NotebookRunStartResponse>({
        method: 'POST',
        path: `${notebookPath}runs/`,
        body: params.variables ? { variables: params.variables } : {},
    })

    const result = await awaitNotebookRun(
        context,
        params.notebook_id,
        notebookPath,
        started.run_id,
        params.wait ? undefined : 0
    )
    return wrapNotebookRunResult({
        ...result,
        cell_count: started.cell_count,
        starts_sandbox: started.starts_sandbox,
        sandbox_hourly_price: started.sandbox_hourly_price ?? null,
    })
}

const tool = (): ToolBase<typeof NotebooksRunSchema, NotebookRunResult> => ({
    name: 'notebooks-run',
    schema: NotebooksRunSchema,
    handler: runNotebookHandler,
})

export default tool
