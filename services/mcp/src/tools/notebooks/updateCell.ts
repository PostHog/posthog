import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import type { Context, ToolBase } from '@/tools/types'

import {
    awaitRun,
    buildResultProp,
    dispatchRun,
    shapeRunForModel,
    wrapRunResultAsInformational,
    type ShapedRunResult,
} from './cellRuns'
import {
    collectRunRefs,
    directDependents,
    findCellTag,
    parseCellTags,
    replaceCellTag,
    startsComponentTag,
    upsertProp,
} from './cellTags'
import { applyMarkdownEdit, fetchMarkdownNotebook, notebookPathFor } from './markdownDoc'
import { NOTEBOOK_SHORT_ID_DESCRIPTION, notebookIdAliases } from './notebookId'

/**
 * Written by `_create_stable_markdown_prose_id` in `products/notebooks/backend/util.py`.
 *
 * Only sharpens an error, because the content parameter decides the branch. A prefix change in
 * the backend therefore degrades one message and breaks nothing.
 */
const PROSE_NODE_ID_PREFIX = 'mdp-'

const UpdateCellInputSchema = z
    .object({
        notebook_id: z.string().describe(NOTEBOOK_SHORT_ID_DESCRIPTION),
        node_id: z.string().describe('The cell to update, as returned by notebooks-add-cell.'),
        code: z
            .string()
            .optional()
            .describe('New SQL or Python source. Omit to re-run the cell as-is (e.g. a stale cell).'),
        markdown: z
            .string()
            .optional()
            .describe(
                'New markdown for a markdown cell: prose, a heading, a table, or a fenced block. Use this instead of `code` when notebooks-get reports the cell as cell_type "markdown". Pass the replacement only; the surrounding cells are untouched.'
            ),
    })
    .strict()

export const NotebooksUpdateCellSchema = z.preprocess(notebookIdAliases('notebook_id'), UpdateCellInputSchema)

export interface UpdateCellResult {
    node_id: string
    run: ShapedRunResult
    stale_dependents: { node_id: string; dataframe_name?: string }[]
}

export interface UpdateProseCellResult {
    node_id: string
    updated: true
}

/** Reject markdown that opens a component tag, so a cell can only be added by the tool that owns runs and identity. */
function assertNoComponentTag(markdown: string): void {
    const offending = markdown.split('\n').find((line) => startsComponentTag(line))
    if (offending) {
        throw new Error(
            `markdown must not contain a component tag (found ${offending.trim().slice(0, 40)}). Add cells with notebooks-add-cell, which assigns identity, names the dataframe, and runs the cell.`
        )
    }
}

/**
 * The offsets come from the state read, so they are right until the document moves under a
 * retry. The source text is the fallback anchor for that case, and an ambiguous or absent
 * match is reported rather than guessed, because a wrong span silently overwrites a neighbour.
 */
function resolveProseSpan(current: string, block: Schemas.NotebookCellState): { start: number; end: number } {
    if (current.slice(block.start, block.end) === block.code) {
        return { start: block.start, end: block.end }
    }
    const first = current.indexOf(block.code)
    if (first === -1 || current.indexOf(block.code, first + block.code.length) !== -1) {
        throw new Error(
            `Cell ${block.node_id} moved or changed since it was read. Re-read the notebook with notebooks-get and retry with the id it returns.`
        )
    }
    return { start: first, end: first + block.code.length }
}

async function updateProseCell(
    context: Context,
    params: z.infer<typeof NotebooksUpdateCellSchema>
): Promise<UpdateProseCellResult> {
    if (params.code !== undefined) {
        throw new Error(
            `Cell ${params.node_id} is a markdown cell. Pass its replacement as \`markdown\`, not \`code\`.`
        )
    }
    const next = params.markdown
    if (next === undefined || !next.trim()) {
        throw new Error('markdown must be non-empty. Remove a cell with notebooks-delete-cell.')
    }
    assertNoComponentTag(next)

    const projectId = await context.stateManager.getProjectId()
    const state = await context.api.request<{ cells: Schemas.NotebookCellState[] }>({
        method: 'GET',
        path: `${notebookPathFor(projectId, params.notebook_id)}sql_v2/state/`,
    })
    const block = state.cells.find((cell) => cell.node_id === params.node_id)
    if (!block) {
        throw new Error(
            `No cell with node_id ${params.node_id} in notebook ${params.notebook_id}. Read the current ids with notebooks-get.`
        )
    }
    if (block.cell_type !== 'markdown') {
        throw new Error(`Cell ${params.node_id} is a ${block.cell_type} cell. Pass its replacement as \`code\`.`)
    }

    await applyMarkdownEdit(context, params.notebook_id, (current) => {
        const span = resolveProseSpan(current, block)
        return current.slice(0, span.start) + next.trim() + current.slice(span.end)
    })
    return { node_id: params.node_id, updated: true }
}

export const updateCellHandler: ToolBase<
    typeof NotebooksUpdateCellSchema,
    UpdateCellResult | UpdateProseCellResult
>['handler'] = async (context: Context, params: z.infer<typeof NotebooksUpdateCellSchema>) => {
    if (params.code !== undefined && params.markdown !== undefined) {
        throw new Error(
            'Pass either code (a SQL or Python cell) or markdown (a markdown cell), not both. The cell type follows from node_id; read it from notebooks-get.'
        )
    }
    if (params.node_id.startsWith(PROSE_NODE_ID_PREFIX) || params.markdown !== undefined) {
        return await updateProseCell(context, params)
    }
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
    let notebook = initial.notebook
    if (params.code !== undefined && params.code !== existing.code) {
        const applied = await applyMarkdownEdit(context, params.notebook_id, (current) => {
            const block = findCellTag(current, params.node_id)
            if (!block) {
                throw new Error(`No cell with node_id ${params.node_id} in notebook ${params.notebook_id}.`)
            }
            return replaceCellTag(current, block, upsertProp(block.source, 'code', params.code))
        })
        markdown = applied.markdown
        // The save response carries the notebook as it stood when the save committed, so it holds a
        // variable edit that landed after the read above.
        notebook = applied.notebook
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
        variables: notebook.variables,
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

const tool = (): ToolBase<typeof NotebooksUpdateCellSchema, UpdateCellResult | UpdateProseCellResult> => ({
    name: 'notebooks-update-cell',
    schema: NotebooksUpdateCellSchema,
    handler: updateCellHandler,
})

export default tool
