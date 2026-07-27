import { v4 as uuidv4 } from 'uuid'
import { z } from 'zod'

import type { Context, ToolBase } from '@/tools/types'

import { awaitRun, buildResultProp, dispatchRun, shapeRunForModel, type ShapedRunResult } from './cellRuns'
import {
    buildCellTag,
    collectRunRefs,
    DATAFRAME_NAME_REGEX,
    findCellTag,
    parseCellTags,
    replaceCellTag,
    uniqueDataframeName,
    upsertProp,
    type CellTagBlock,
} from './cellTags'
import { applyMarkdownEdit, fetchMarkdownNotebook, notebookPathFor } from './markdownDoc'

export const NotebooksAddCellSchema = z
    .object({
        notebook_id: z.string().describe('The notebook short_id (the public id in the URL, e.g. `aBcD1234`).'),
        cell_type: z
            .enum(['sql', 'python', 'markdown', 'saved_insight'])
            .describe(
                "Cell kind: 'sql' (HogQL against PostHog data) and 'python' run immediately; 'markdown' inserts prose; 'saved_insight' embeds an existing insight."
            ),
        code: z.string().optional().describe('The SQL or Python source. Required for sql/python cells.'),
        markdown: z.string().optional().describe('Prose to insert. Required for markdown cells.'),
        insight_short_id: z
            .string()
            .optional()
            .describe('Short id of the saved insight to embed. Required for saved_insight cells.'),
        dataframe_name: z
            .string()
            .regex(DATAFRAME_NAME_REGEX)
            .optional()
            .describe(
                'Name other cells use to reference this cell\'s result dataframe (e.g. in SQL joins or Python code). Auto-assigned ("sql_df", "df", …) when omitted for sql/python cells.'
            ),
        after_node_id: z
            .string()
            .optional()
            .describe('Insert after this cell (node_id from a previous add). Defaults to the end of the document.'),
    })
    .strict()

export interface AddCellResult {
    node_id?: string
    dataframe_name?: string
    run?: ShapedRunResult
}

function insertBlock(markdown: string, block: string, afterNodeId: string | undefined): string {
    const trimmed = markdown.replace(/\s+$/, '')
    if (afterNodeId) {
        const anchor = findCellTag(markdown, afterNodeId)
        if (!anchor) {
            throw new Error(`No cell with node_id ${afterNodeId} found to insert after.`)
        }
        return `${markdown.slice(0, anchor.end)}\n\n${block}${markdown.slice(anchor.end)}`
    }
    return trimmed ? `${trimmed}\n\n${block}\n` : `${block}\n`
}

async function runAndWriteBack(
    context: Context,
    notebookId: string,
    nodeId: string,
    nodeType: 'hogql' | 'python',
    code: string,
    outputName: string,
    cells: CellTagBlock[]
): Promise<ShapedRunResult> {
    const projectId = await context.stateManager.getProjectId()
    const notebookPath = notebookPathFor(projectId, notebookId)
    const refs = collectRunRefs(cells, nodeId)
    const runId = await dispatchRun(context, notebookPath, {
        node_id: nodeId,
        node_type: nodeType,
        code,
        output_name: outputName,
        refs,
    })
    const outcome = await awaitRun(context, notebookPath, runId)
    // Mirror the editor's write-back so humans opening the notebook see the result: runId
    // always, the envelope once terminal. Anchored on nodeId, so concurrent edits to other
    // parts of the document survive the retry inside applyMarkdownEdit.
    await applyMarkdownEdit(context, notebookId, (markdown) => {
        const block = findCellTag(markdown, nodeId)
        if (!block) {
            return markdown
        }
        let source = upsertProp(block.source, 'runId', runId)
        if (outcome.envelope && (outcome.status === 'done' || outcome.status === 'interrupted')) {
            source = upsertProp(source, 'result', buildResultProp(outcome.envelope))
        }
        return replaceCellTag(markdown, block, source)
    })
    return shapeRunForModel(outcome)
}

export const addCellHandler: ToolBase<typeof NotebooksAddCellSchema, AddCellResult>['handler'] = async (
    context: Context,
    params: z.infer<typeof NotebooksAddCellSchema>
) => {
    if ((params.cell_type === 'sql' || params.cell_type === 'python') && !params.code?.trim()) {
        throw new Error(`A ${params.cell_type} cell requires non-empty code.`)
    }
    if (params.cell_type === 'markdown' && !params.markdown?.trim()) {
        throw new Error('A markdown cell requires non-empty markdown.')
    }
    if (params.cell_type === 'saved_insight' && !params.insight_short_id?.trim()) {
        throw new Error('A saved_insight cell requires insight_short_id.')
    }

    if (params.cell_type === 'markdown') {
        await applyMarkdownEdit(context, params.notebook_id, (markdown) =>
            insertBlock(markdown, params.markdown!.trim(), params.after_node_id)
        )
        return {}
    }

    const nodeId = uuidv4()

    if (params.cell_type === 'saved_insight') {
        const tag = buildCellTag('Query', {
            nodeId,
            query: { kind: 'SavedInsightNode', shortId: params.insight_short_id },
            hideFilters: true,
        })
        await applyMarkdownEdit(context, params.notebook_id, (markdown) =>
            insertBlock(markdown, tag, params.after_node_id)
        )
        return { node_id: nodeId }
    }

    const tagName = params.cell_type === 'sql' ? 'SQLV2' : 'PythonV2'
    const initial = await fetchMarkdownNotebook(context, params.notebook_id)
    const dataframeName =
        params.dataframe_name ??
        uniqueDataframeName(params.cell_type === 'sql' ? 'sql_df' : 'df', parseCellTags(initial.markdown))
    const tag = buildCellTag(tagName, { nodeId, code: params.code, returnVariable: dataframeName })

    const { markdown } = await applyMarkdownEdit(context, params.notebook_id, (current) =>
        insertBlock(current, tag, params.after_node_id)
    )
    const run = await runAndWriteBack(
        context,
        params.notebook_id,
        nodeId,
        params.cell_type === 'sql' ? 'hogql' : 'python',
        params.code!,
        dataframeName,
        parseCellTags(markdown)
    )
    return { node_id: nodeId, dataframe_name: dataframeName, run }
}

const tool = (): ToolBase<typeof NotebooksAddCellSchema, AddCellResult> => ({
    name: 'notebooks-add-cell',
    schema: NotebooksAddCellSchema,
    handler: addCellHandler,
})

export default tool
