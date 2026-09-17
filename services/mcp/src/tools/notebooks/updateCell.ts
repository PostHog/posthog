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
    normalizeForTagScan,
    startsComponentTag,
    upsertProp,
} from './cellTags'
import { applyMarkdownEdit, fetchMarkdownNotebook, notebookPathFor, saveMarkdown } from './markdownDoc'
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
    let insideFence = false
    // The backend collapses `\r\n` and a lone `\r` to a newline before it looks for tags, so a
    // payload split only on `\n` hides a tag from this guard that the backend later reads as a
    // live cell.
    for (const line of markdown.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n')) {
        // Fence detection normalizes the same characters as the tag check. Python strips them,
        // so a control-prefixed fence opens a block there and reads as prose here, which moves
        // every tag after it in or out of the fence.
        if (normalizeForTagScan(line).startsWith('```')) {
            insideFence = !insideFence
            continue
        }
        // Both walkers read fenced content as inert, so a tag written as an example there opens
        // no cell and the guard would reject a legitimate edit.
        if (insideFence || !startsComponentTag(line)) {
            continue
        }
        throw new Error(
            `markdown must not contain a component tag (found ${line.trim().slice(0, 40)}). Add cells with notebooks-add-cell, which assigns identity, names the dataframe, and runs the cell. To show a tag as an example, put it in a fenced code block.`
        )
    }
    // An unclosed fence flips the fence state of everything after this block, which decides
    // whether the tags already in the document open cells.
    if (insideFence) {
        throw new Error('markdown must not leave a code fence open. Close every ``` block in the replacement.')
    }
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
    const state = await context.api.request<{ version: number | null; cells: Schemas.NotebookCellState[] }>({
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
    // A prose id counts occurrences of identical text, so a block that duplicates another one's
    // text is only pinned by the position it held when the caller read it. A write arrives after
    // that read, and an identical block inserted above in between shifts every later occurrence
    // by one. The id would still resolve, and the fresh offsets would still validate, so the edit
    // would land on a block the caller never saw.
    const sameId = state.cells.filter((cell) => cell.node_id === params.node_id)
    if (sameId.length > 1) {
        throw new Error(
            `Cell ${params.node_id} names ${sameId.length} blocks in notebook ${params.notebook_id}, so it cannot name one of them. Re-read the notebook with notebooks-get.`
        )
    }
    // The edit is bound to the document the caller read, rather than hunted for again in a newer
    // one. Re-resolving needs the backend's block grammar, and this side does not have it: a tag
    // `parseCellTags` cannot see is prose here and a live cell there, so a miss rewrites a cell.
    // A changed document is therefore reported, and the caller reads again.
    const notebook = await fetchMarkdownNotebook(context, params.notebook_id)
    if (notebook.version !== state.version) {
        throw new Error(
            `Notebook ${params.notebook_id} changed since cell ${params.node_id} was read. Read it again with notebooks-get and retry with the id it returns.`
        )
    }
    if (notebook.markdown.slice(block.start, block.end) !== block.code) {
        throw new Error(
            `Cell ${params.node_id} is not where the read placed it in notebook ${params.notebook_id}. Read it again with notebooks-get and retry with the id it returns.`
        )
    }

    const nextMarkdown = notebook.markdown.slice(0, block.start) + next.trim() + notebook.markdown.slice(block.end)
    await saveMarkdown(context, notebook, nextMarkdown)
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
