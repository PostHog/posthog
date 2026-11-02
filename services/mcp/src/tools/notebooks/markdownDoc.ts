import { v4 as uuidv4 } from 'uuid'

import type { Schemas } from '@/api/generated'
import type { Context } from '@/tools/types'

const MARKDOWN_NOTEBOOK_NODE_TYPE = 'ph-markdown-notebook'
const MARKDOWN_NOTEBOOK_NODE_ID = 'markdown-notebook-v2'

export interface MarkdownNotebookState {
    notebookPath: string
    notebook: Schemas.Notebook
    version: number
    markdown: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function getMarkdownNotebookNode(content: unknown): Record<string, unknown> | null {
    if (!isRecord(content)) {
        return null
    }
    const nodes = content.content
    if (!Array.isArray(nodes) || nodes.length !== 1) {
        return null
    }
    const node = nodes[0]
    if (!isRecord(node) || node.type !== MARKDOWN_NOTEBOOK_NODE_TYPE) {
        return null
    }
    const attrs = node.attrs
    if (!isRecord(attrs) || typeof attrs.markdown !== 'string') {
        return null
    }
    return node
}

export function buildMarkdownNotebookContent(markdown: string, nodeId: string = MARKDOWN_NOTEBOOK_NODE_ID): unknown {
    return {
        type: 'doc',
        content: [{ type: MARKDOWN_NOTEBOOK_NODE_TYPE, attrs: { nodeId, markdown } }],
    }
}

export function notebookPathFor(projectId: string, shortId: string): string {
    return `/api/projects/${encodeURIComponent(projectId)}/notebooks/${encodeURIComponent(shortId)}/`
}

export async function fetchMarkdownNotebook(context: Context, shortId: string): Promise<MarkdownNotebookState> {
    const projectId = await context.stateManager.getProjectId()
    const notebookPath = notebookPathFor(projectId, shortId)
    const notebook = await context.api.request<Schemas.Notebook>({ method: 'GET', path: notebookPath })
    if (typeof notebook.version !== 'number') {
        throw new Error(`Notebook ${shortId} has no numeric version — required for optimistic concurrency.`)
    }
    const node = getMarkdownNotebookNode(notebook.content)
    if (node === null) {
        throw new Error(
            `Notebook ${shortId} is not a markdown notebook. Cell tools only work on markdown notebooks — create one with notebooks-create-markdown.`
        )
    }
    const attrs = node.attrs as Record<string, unknown>
    return { notebookPath, notebook, version: notebook.version, markdown: attrs.markdown as string }
}

export async function saveMarkdown(
    context: Context,
    state: MarkdownNotebookState,
    nextMarkdown: string
): Promise<Schemas.Notebook> {
    const content = structuredClone(state.notebook.content) as Record<string, unknown>
    const node = getMarkdownNotebookNode(content)
    if (node === null) {
        throw new Error('Notebook content is no longer a markdown notebook document.')
    }
    node.attrs = { ...(node.attrs as Record<string, unknown>), markdown: nextMarkdown }
    return await context.api.request<Schemas.Notebook>({
        method: 'POST',
        path: `${state.notebookPath}collab/markdown_save/`,
        body: {
            client_id: uuidv4(),
            version: state.version,
            content,
            text_content: nextMarkdown,
        },
    })
}

/**
 * Read-modify-write anchored on a pure markdown transform, retried once on a version
 * conflict. The transform re-applies against freshly read markdown, so a concurrent edit
 * elsewhere in the document never clobbers it — cell edits are tag-block surgery keyed on
 * nodeId, which stays applicable after unrelated changes.
 */
export async function applyMarkdownEdit(
    context: Context,
    shortId: string,
    transform: (markdown: string, version: number) => string
): Promise<{ notebook: Schemas.Notebook; markdown: string }> {
    let lastError: unknown
    for (let attempt = 0; attempt < 2; attempt++) {
        const state = await fetchMarkdownNotebook(context, shortId)
        const nextMarkdown = transform(state.markdown, state.version)
        if (nextMarkdown === state.markdown) {
            // Saving identical content only bumps the version and tells every collaborator the
            // document changed. A repeated write-back is the case this spares them.
            return { notebook: state.notebook, markdown: state.markdown }
        }
        try {
            const notebook = await saveMarkdown(context, state, nextMarkdown)
            return { notebook, markdown: nextMarkdown }
        } catch (error) {
            lastError = error
            const status = (error as { status?: number }).status
            if (status !== 409 && status !== 410) {
                throw error
            }
        }
    }
    throw lastError
}

export async function replaceMarkdownCell(
    context: Context,
    notebookId: string,
    nodeId: string,
    replacement: string
): Promise<void> {
    const projectId = await context.stateManager.getProjectId()
    const state = await context.api.request<{ version: number | null; cells: Schemas.NotebookCellState[] }>({
        method: 'GET',
        path: `${notebookPathFor(projectId, notebookId)}sql_v2/state/`,
    })
    const block = state.cells.find((cell) => cell.node_id === nodeId)
    if (!block) {
        throw new Error(
            `No cell with node_id ${nodeId} in notebook ${notebookId}. Read the current ids with notebooks-get.`
        )
    }
    if (block.cell_type !== 'markdown') {
        throw new Error(`Cell ${nodeId} is a ${block.cell_type} cell. Pass its replacement as \`code\`.`)
    }
    // A prose id counts occurrences of identical text, so a block that duplicates another one's
    // text is only pinned by the position it held when the caller read it. A write arrives after
    // that read, and an identical block inserted above in between shifts every later occurrence
    // by one. The id would still resolve, and the fresh offsets would still validate, so the edit
    // would land on a block the caller never saw.
    const sameId = state.cells.filter((cell) => cell.node_id === nodeId)
    if (sameId.length > 1) {
        throw new Error(
            `Cell ${nodeId} names ${sameId.length} blocks in notebook ${notebookId}, so it cannot name one of them. Re-read the notebook with notebooks-get.`
        )
    }
    // The edit is bound to the document the caller read, rather than hunted for again in a newer
    // one. Re-resolving needs the backend's block grammar, and this side does not have it: a tag
    // `parseCellTags` cannot see is prose here and a live cell there, so a miss rewrites a cell.
    // A changed document is therefore reported, and the caller reads again.
    const notebook = await fetchMarkdownNotebook(context, notebookId)
    if (notebook.version !== state.version) {
        throw new Error(
            `Notebook ${notebookId} changed since cell ${nodeId} was read. Read it again with notebooks-get and retry with the id it returns.`
        )
    }
    if (notebook.markdown.slice(block.start, block.end) !== block.code) {
        throw new Error(
            `Cell ${nodeId} is not where the read placed it in notebook ${notebookId}. Read it again with notebooks-get and retry with the id it returns.`
        )
    }

    let start = block.start
    if (!replacement) {
        const anchor = /<!--ph:(phb-[A-Za-z0-9._-]{1,124})-->(?:\r\n|\r|\n)$/.exec(notebook.markdown.slice(0, start))
        if (anchor?.[1] === nodeId) {
            start = anchor.index
        }
    }
    const nextMarkdown = notebook.markdown.slice(0, start) + replacement + notebook.markdown.slice(block.end)
    await saveMarkdown(context, notebook, nextMarkdown)
}
