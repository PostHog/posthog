import { v4 as uuidv4 } from 'uuid'
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
import {
    buildCellTag,
    collectRunRefs,
    COMPONENT_TAG_REGEX,
    DATAFRAME_NAME_REGEX,
    findCellTag,
    parseCellTags,
    replaceCellTag,
    uniqueDataframeName,
    upsertProp,
    type CellTagBlock,
} from './cellTags'
import { applyMarkdownEdit, fetchMarkdownNotebook, notebookPathFor } from './markdownDoc'
import { getNotebookWidgetTagNames, getNotebookWidgetViewError } from './widgetCatalog'

/** The cell header renders a title on a single ellipsized line, so anything longer is cut off anyway. */
const CELL_TITLE_MAX_LENGTH = 120

export const NotebooksAddCellSchema = z
    .object({
        notebook_id: z.string().describe('The notebook short_id (the public id in the URL, e.g. `aBcD1234`).'),
        cell_type: z
            .enum(['sql', 'python', 'markdown', 'saved_insight', 'component'])
            .describe(
                "Cell kind: 'sql' (HogQL against PostHog data) and 'python' run immediately; 'markdown' inserts prose (headings, tables, code/mermaid fences); 'saved_insight' embeds an existing insight; 'component' inserts any other notebook component tag (charts, media, PostHog entities)."
            ),
        code: z.string().optional().describe('The SQL or Python source. Required for sql/python cells.'),
        markdown: z.string().optional().describe('Prose to insert. Required for markdown cells.'),
        insight_short_id: z
            .string()
            .optional()
            .describe('Short id of the saved insight to embed. Required for saved_insight cells.'),
        tag_name: z
            .string()
            .regex(COMPONENT_TAG_REGEX)
            .optional()
            .describe(
                `Component cells: the notebook component to insert. Object widgets with named views: ${getNotebookWidgetTagNames().join(', ')}. Other components include Query (product analytics charts and event tables via its query prop), Image, Embed, Latex, Person, Recording, and RecordingPlaylist. Executable cells are not allowed here — use cell_type sql/python.`
            ),
        props: z
            .record(z.string(), z.unknown())
            .optional()
            .describe(
                'Component cells: the props for the tag, matching what the notebook UI stores for that component. Object widgets take their identity prop plus an optional view, for example {"id": 123, "view": "summary"}. For Query: {"query": {"kind": "InsightVizNode", "source": <TrendsQuery|FunnelsQuery|RetentionQuery|PathsQuery|StickinessQuery|LifecycleQuery>}} for insights, or {"query": {"kind": "DataTableNode", "source": {"kind": "EventsQuery", …}}} for event tables. HogQLQuery sources are not accepted here — use cell_type sql, which charts its result too.'
            ),
        dataframe_name: z
            .string()
            .regex(DATAFRAME_NAME_REGEX)
            .optional()
            .describe(
                'Name other cells use to reference this cell\'s result dataframe (e.g. in SQL joins or Python code). Auto-assigned ("sql_df", "df", …) when omitted for sql/python cells.'
            ),
        title: z
            .string()
            .max(CELL_TITLE_MAX_LENGTH)
            .optional()
            .describe(
                'Short label shown in the cell header, e.g. "Weekly signups by source". Set it on every cell you add so a reader can skim the notebook without reading the code — say what the cell shows, not that it is SQL or Python. Not accepted for markdown cells; give those a markdown heading instead.'
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

/**
 * One blank line separates two blocks of the same card in the notebook editor; a second one starts
 * a new card. Cells added here are nodes in their own right, so they are separated on both sides —
 * otherwise consecutive markdown cells land as one card (`startsGroup` in the editor's types.ts).
 */
const BLOCK_SEPARATOR = '\n\n\n'

function insertBlock(markdown: string, block: string, afterNodeId: string | undefined): string {
    const trimmed = markdown.replace(/\s+$/, '')
    if (afterNodeId) {
        const anchor = findCellTag(markdown, afterNodeId)
        if (!anchor) {
            throw new Error(`No cell with node_id ${afterNodeId} found to insert after.`)
        }
        const rest = markdown.slice(anchor.end).replace(/^\n+/, '')
        const head = `${markdown.slice(0, anchor.end)}${BLOCK_SEPARATOR}${block}`
        return rest ? `${head}${BLOCK_SEPARATOR}${rest}` : `${head}\n`
    }
    return trimmed ? `${trimmed}${BLOCK_SEPARATOR}${block}\n` : `${block}\n`
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

/**
 * A `<Query>` whose source is HogQL is the legacy SQL cell. It renders a result table or chart but
 * does not run through the sandbox, so it names no dataframe other cells can reference and keeps no
 * run history. SQLV2 (cell_type 'sql') supersedes it and charts its result the same way, so SQL
 * authored over MCP must land there. The editor's insert menu makes the same choice behind the
 * revamped-py-notebooks flag that gates this tool.
 */
function hasHogQLQuerySource(props: Record<string, unknown> | undefined): boolean {
    const query = props?.query
    if (!query || typeof query !== 'object') {
        return false
    }
    const { kind, source } = query as { kind?: unknown; source?: unknown }
    if (kind === 'HogQLQuery') {
        return true
    }
    return !!source && typeof source === 'object' && (source as { kind?: unknown }).kind === 'HogQLQuery'
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
    if (params.cell_type === 'component') {
        if (!params.tag_name) {
            throw new Error('A component cell requires tag_name.')
        }
        // Executable and deprecated tags must go through their owning cell types so runs,
        // identity, and result write-back stay consistent.
        if (['SQLV2', 'PythonV2', 'Python', 'DuckSQL', 'HogQLSQL'].includes(params.tag_name)) {
            throw new Error(
                `Use cell_type 'sql' or 'python' for executable cells instead of tag_name ${params.tag_name}.`
            )
        }
        if (hasHogQLQuerySource(params.props)) {
            throw new Error(
                "Use cell_type 'sql' for SQL instead of a component with a HogQLQuery source. A sql cell runs the query, names a dataframe other cells can reference, and charts its result."
            )
        }
        const widgetViewError = getNotebookWidgetViewError(params.tag_name, params.props?.view)
        if (widgetViewError) {
            throw new Error(widgetViewError)
        }
    }

    const title = params.title?.trim() || undefined

    if (params.cell_type === 'markdown') {
        if (title) {
            throw new Error(
                'A markdown cell has no header to title — put the heading in the markdown itself (e.g. "## Weekly signups").'
            )
        }
        await applyMarkdownEdit(context, params.notebook_id, (markdown) =>
            insertBlock(markdown, params.markdown!.trim(), params.after_node_id)
        )
        return {}
    }

    const nodeId = uuidv4()

    if (params.cell_type === 'saved_insight') {
        const tag = buildCellTag('Query', {
            nodeId,
            title,
            query: { kind: 'SavedInsightNode', shortId: params.insight_short_id },
        })
        await applyMarkdownEdit(context, params.notebook_id, (markdown) =>
            insertBlock(markdown, tag, params.after_node_id)
        )
        return { node_id: nodeId }
    }

    if (params.cell_type === 'component') {
        // `title` last only when set, so a component that carries its own title prop keeps it.
        const tag = buildCellTag(params.tag_name!, { ...params.props, nodeId, ...(title ? { title } : {}) })
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
    const tag = buildCellTag(tagName, { nodeId, title, code: params.code, returnVariable: dataframeName })

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
    return wrapRunResultAsInformational({ node_id: nodeId, dataframe_name: dataframeName, run })
}

const tool = (): ToolBase<typeof NotebooksAddCellSchema, AddCellResult> => ({
    name: 'notebooks-add-cell',
    schema: NotebooksAddCellSchema,
    handler: addCellHandler,
})

export default tool
