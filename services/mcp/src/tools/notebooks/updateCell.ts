import { z } from 'zod'

import type { Context, ToolBase } from '@/tools/types'

import {
    awaitRun,
    buildResultProp,
    dispatchRun,
    shapeRunForModel,
    wrapRunResultAsInformational,
    type ShapedRunResult,
} from './cellRuns'
import { collectRunRefs, directDependents, findCellTag, parseCellTags, replaceCellTag, upsertProp } from './cellTags'
import { applyMarkdownEdit, fetchMarkdownNotebook, notebookPathFor } from './markdownDoc'

export const NotebooksUpdateCellSchema = z
    .object({
        notebook_id: z.string().describe('The notebook short_id (the public id in the URL, e.g. `aBcD1234`).'),
        node_id: z.string().describe('The cell to update, as returned by notebooks-add-cell.'),
        code: z
            .string()
            .optional()
            .describe('New SQL or Python source. Omit to re-run the cell as-is (e.g. a stale cell).'),
    })
    .strict()

export interface UpdateCellResult {
    node_id: string
    run: ShapedRunResult
    stale_dependents: { node_id: string; dataframe_name?: string }[]
}

export const updateCellHandler: ToolBase<typeof NotebooksUpdateCellSchema, UpdateCellResult>['handler'] = async (
    context: Context,
    params: z.infer<typeof NotebooksUpdateCellSchema>
) => {
    if (params.code !== undefined && !params.code.trim()) {
        throw new Error('code must be non-empty; omit it to re-run the cell unchanged.')
    }

    const initial = await fetchMarkdownNotebook(context, params.notebook_id)
    const existing = findCellTag(initial.markdown, params.node_id)
    if (!existing) {
        throw new Error(`No cell with node_id ${params.node_id} in notebook ${params.notebook_id}.`)
    }
    if (existing.tagName !== 'SQLV2' && existing.tagName !== 'PythonV2') {
        throw new Error(
            `Cell ${params.node_id} is a ${existing.tagName} cell and cannot be updated with this tool — delete and re-add it instead.`
        )
    }

    let markdown = initial.markdown
    if (params.code !== undefined && params.code !== existing.code) {
        const applied = await applyMarkdownEdit(context, params.notebook_id, (current) => {
            const block = findCellTag(current, params.node_id)
            if (!block) {
                throw new Error(`No cell with node_id ${params.node_id} in notebook ${params.notebook_id}.`)
            }
            return replaceCellTag(current, block, upsertProp(block.source, 'code', params.code))
        })
        markdown = applied.markdown
    }

    const code = params.code ?? existing.code
    if (!code.trim()) {
        throw new Error(`Cell ${params.node_id} has no code to run.`)
    }

    const projectId = await context.stateManager.getProjectId()
    const notebookPath = notebookPathFor(projectId, params.notebook_id)
    const cells = parseCellTags(markdown)
    const runId = await dispatchRun(context, notebookPath, {
        node_id: params.node_id,
        node_type: existing.tagName === 'SQLV2' ? 'hogql' : 'python',
        code,
        output_name: existing.returnVariable,
        refs: collectRunRefs(cells, params.node_id),
    })
    const outcome = await awaitRun(context, notebookPath, runId)
    await applyMarkdownEdit(context, params.notebook_id, (current) => {
        const block = findCellTag(current, params.node_id)
        if (!block) {
            return current
        }
        let source = upsertProp(block.source, 'runId', runId)
        if (outcome.envelope && (outcome.status === 'done' || outcome.status === 'interrupted')) {
            source = upsertProp(source, 'result', buildResultProp(outcome.envelope))
        }
        return replaceCellTag(current, block, source)
    })

    return wrapRunResultAsInformational({
        node_id: params.node_id,
        run: shapeRunForModel(outcome),
        stale_dependents:
            outcome.status === 'done' ? directDependents(cells, existing.returnVariable, params.node_id) : [],
    })
}

const tool = (): ToolBase<typeof NotebooksUpdateCellSchema, UpdateCellResult> => ({
    name: 'notebooks-update-cell',
    schema: NotebooksUpdateCellSchema,
    handler: updateCellHandler,
})

export default tool
