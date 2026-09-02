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
    transform: (markdown: string) => string
): Promise<{ notebook: Schemas.Notebook; markdown: string }> {
    let lastError: unknown
    for (let attempt = 0; attempt < 2; attempt++) {
        const state = await fetchMarkdownNotebook(context, shortId)
        const nextMarkdown = transform(state.markdown)
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
