/**
 * `notebook-edit` tool.
 *
 * Content replacement for notebooks. Markdown notebooks use native markdown
 * string replacement: `{ short_id, old_markdown, new_markdown, replace_all? }`.
 * Legacy rich-text notebooks use JSON subtree replacement:
 * `{ short_id, old_value, new_value, replace_all? }`.
 *
 * Markdown edits POST the full markdown notebook document to
 * `/collab/markdown_save` so other connected clients receive markdown diffs.
 * Legacy JSON edits are expressed as a single ProseMirror ReplaceStep and
 * POSTed to `/collab/save`.
 *
 * Server errors (409 concurrent edit, 410 stale buffer, etc.) flow through
 * `context.api.request` → PostHogApiError → `handleToolError`, which surfaces
 * the URL, status, and Django response body verbatim to the agent. The 409
 * body already includes the latest version + rebased steps, which the agent
 * can use to retry without an extra read.
 */
import { isDeepStrictEqual } from 'node:util'
import { Fragment, Node } from 'prosemirror-model'
import { type Step, Transform } from 'prosemirror-transform'
import { v4 as uuidv4 } from 'uuid'
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { buildSchemaForDoc, packDocAttrs, type ProseMirrorNodeJSON, unpackDocAttrs } from '@/lib/prosemirror/schema'
import type { Context, ToolBase } from '@/tools/types'

const MARKDOWN_NOTEBOOK_NODE_TYPE = 'ph-markdown-notebook'
const ERROR_PREVIEW_LENGTH = 160

const Subtree = z.union([z.record(z.string(), z.unknown()), z.array(z.unknown())])

const BaseEditSchema = z.object({
    short_id: z.string().describe('The notebook short_id (the public id in the URL, e.g. `aBcD1234`).'),
    replace_all: z
        .boolean()
        .optional()
        .describe(
            'Replace every matching occurrence. Default false — the tool errors out if the target is not unique.'
        ),
})

const MarkdownEditSchema = BaseEditSchema.extend({
    old_markdown: z
        .string()
        .min(1)
        .describe(
            'Markdown text to find inside a markdown notebook. Get the current markdown with `execute-sql` from `system.notebooks.markdown`; pass the full markdown body to replace the whole notebook, or a unique markdown span to make a local edit.'
        ),
    new_markdown: z
        .string()
        .describe(
            'Markdown text to put in place of `old_markdown`. This is plain notebook markdown; do not wrap it in ProseMirror JSON.'
        ),
})
    .strict()
    .refine((v) => v.old_markdown !== v.new_markdown, {
        message: 'old_markdown and new_markdown must differ',
        path: ['new_markdown'],
    })

const JsonEditSchema = BaseEditSchema.extend({
    old_value: Subtree.describe(
        'Legacy rich-text notebook mode only. The JSON subtree to find. For markdown notebooks, use `old_markdown` instead of copying nested `ph-markdown-notebook` JSON.'
    ),
    new_value: Subtree.describe(
        'Legacy rich-text notebook mode only. The JSON subtree to put in place of `old_value`. For markdown notebooks, use `new_markdown`.'
    ),
})
    .strict()
    .refine((v) => !isDeepStrictEqual(v.old_value, v.new_value), {
        message: 'old_value and new_value must differ',
        path: ['new_value'],
    })

export const NotebookEditSchema = z.union([MarkdownEditSchema, JsonEditSchema])

type MarkdownParams = z.infer<typeof MarkdownEditSchema>
type JsonParams = z.infer<typeof JsonEditSchema>
type Params = z.infer<typeof NotebookEditSchema>

function isMarkdownParams(params: Params): params is MarkdownParams {
    return 'old_markdown' in params
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
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

function buildMarkdownNotebookContent(content: unknown, markdown: string): ProseMirrorNodeJSON {
    const clonedContent = structuredClone(content) as ProseMirrorNodeJSON
    const node = getMarkdownNotebookNode(clonedContent)
    if (node === null || !isRecord(node.attrs)) {
        throw new Error('Notebook content is no longer a markdown notebook document.')
    }
    node.attrs = { ...node.attrs, markdown }
    return clonedContent
}

function truncateForError(value: string): string {
    const normalized = value.replace(/\s+/g, ' ').trim()
    if (normalized.length <= ERROR_PREVIEW_LENGTH) {
        return normalized
    }
    return `${normalized.slice(0, ERROR_PREVIEW_LENGTH)}...`
}

function safeJsonStringify(value: unknown): string {
    try {
        return JSON.stringify(value)
    } catch {
        return '[unserializable JSON value]'
    }
}

function topLevelNodeCount(content: unknown): number | null {
    if (!isRecord(content) || !Array.isArray(content.content)) {
        return null
    }
    return content.content.length
}

function countStringMatches(value: string, target: string): number {
    let count = 0
    let start = 0
    while (start <= value.length) {
        const index = value.indexOf(target, start)
        if (index === -1) {
            return count
        }
        count++
        start = index + target.length
    }
    return count
}

function replaceMarkdown(currentMarkdown: string, params: MarkdownParams): string {
    const matches = countStringMatches(currentMarkdown, params.old_markdown)
    if (matches === 0) {
        throw new Error(
            'old_markdown was not found in the notebook markdown. The match is exact, including whitespace. ' +
                `Current markdown length: ${currentMarkdown.length} characters. ` +
                `old_markdown length: ${params.old_markdown.length} characters. ` +
                `old_markdown preview: ${truncateForError(params.old_markdown)}. ` +
                'Use `execute-sql` to refresh `system.notebooks.markdown` for this short_id.'
        )
    }

    if (matches > 1 && params.replace_all !== true) {
        throw new Error(
            `old_markdown matches ${matches} places in the notebook markdown. ` +
                'Pass a longer unique markdown span, or set `replace_all: true` to replace every match.'
        )
    }

    if (params.replace_all === true) {
        return currentMarkdown.split(params.old_markdown).join(params.new_markdown)
    }

    const index = currentMarkdown.indexOf(params.old_markdown)
    return (
        currentMarkdown.slice(0, index) +
        params.new_markdown +
        currentMarkdown.slice(index + params.old_markdown.length)
    )
}

async function fetchNotebookMarkdown(context: Context, notebookPath: string): Promise<string | null> {
    const result = await context.api.request<{ markdown: string | null }>({
        method: 'GET',
        path: `${notebookPath}markdown/`,
    })
    return result.markdown
}

async function editMarkdownNotebook(
    context: Context,
    notebookPath: string,
    notebook: Schemas.Notebook,
    params: MarkdownParams
): Promise<Schemas.Notebook> {
    const currentMarkdown = await fetchNotebookMarkdown(context, notebookPath)
    if (currentMarkdown === null) {
        throw new Error(
            `Notebook ${params.short_id} is not a markdown notebook. ` +
                'Use `old_value`/`new_value` JSON subtree replacement for legacy rich-text notebooks.'
        )
    }

    if (getMarkdownNotebookNode(notebook.content) === null) {
        throw new Error(
            `Notebook ${params.short_id} content is not a markdown notebook document. ` +
                'Use `old_value`/`new_value` JSON subtree replacement for legacy rich-text notebooks.'
        )
    }

    const nextMarkdown = replaceMarkdown(currentMarkdown, params)
    const nextContent = buildMarkdownNotebookContent(notebook.content, nextMarkdown)

    return await context.api.request<Schemas.Notebook>({
        method: 'POST',
        path: `${notebookPath}collab/markdown_save/`,
        body: {
            client_id: uuidv4(),
            version: notebook.version,
            content: nextContent as unknown as Record<string, unknown>,
            text_content: nextMarkdown,
        },
    })
}

/** Counts subtrees deep-equal to `target`; lets the handler reject bad inputs before mutating. */
function countMatches(tree: unknown, target: unknown): number {
    let count = 0
    const walk = (node: unknown): void => {
        if (isDeepStrictEqual(node, target)) {
            count++
            return
        }
        if (Array.isArray(node)) {
            node.forEach(walk)
        } else if (node !== null && typeof node === 'object') {
            Object.values(node).forEach(walk)
        }
    }
    walk(tree)
    return count
}

/**
 * Walks `tree` and replaces every subtree that deep-equals `target`.
 * When `replaceAll` is false, only the first match is replaced.
 */
function deepReplace<T>(tree: T, target: unknown, replacement: unknown, replaceAll: boolean): T {
    let replaced = 0
    const walk = (node: unknown): unknown => {
        if (isDeepStrictEqual(node, target)) {
            if (!replaceAll && replaced > 0) {
                return node
            }
            replaced++
            return structuredClone(replacement)
        }
        if (Array.isArray(node)) {
            return node.map(walk)
        }
        if (node !== null && typeof node === 'object') {
            return Object.fromEntries(Object.entries(node).map(([k, v]) => [k, walk(v)]))
        }
        return node
    }
    return walk(tree) as T
}

/**
 * Single ReplaceStep covering the smallest top-level block range that differs.
 * Block-level (not character-level).
 */
function buildMinimalSteps(oldDoc: Node, newDoc: Node): Step[] {
    const oldContent = oldDoc.content
    const newContent = newDoc.content
    const oldCount = oldContent.childCount
    const newCount = newContent.childCount

    // Walk in from the start until blocks diverge.
    let startIdx = 0
    while (startIdx < oldCount && startIdx < newCount && oldContent.child(startIdx).eq(newContent.child(startIdx))) {
        startIdx++
    }

    // Walk in from the end until blocks diverge (without crossing startIdx).
    let oldEndIdx = oldCount
    let newEndIdx = newCount
    while (
        oldEndIdx > startIdx &&
        newEndIdx > startIdx &&
        oldContent.child(oldEndIdx - 1).eq(newContent.child(newEndIdx - 1))
    ) {
        oldEndIdx--
        newEndIdx--
    }

    // Identical docs — nothing to send.
    if (startIdx === oldEndIdx && startIdx === newEndIdx) {
        return []
    }

    // Convert block indices to doc positions.
    let fromPos = 0
    for (let i = 0; i < startIdx; i++) {
        fromPos += oldContent.child(i).nodeSize
    }
    let toPos = fromPos
    for (let i = startIdx; i < oldEndIdx; i++) {
        toPos += oldContent.child(i).nodeSize
    }

    // Replacement is the slice of new blocks in [startIdx, newEndIdx).
    const replacementBlocks: Node[] = []
    for (let i = startIdx; i < newEndIdx; i++) {
        replacementBlocks.push(newContent.child(i))
    }

    return new Transform(oldDoc).replaceWith(fromPos, toPos, Fragment.from(replacementBlocks)).steps
}

/**
 * Plain-text view for the search index.
 * Mirrors what the frontend's `editor.getText()` produces.
 */
function buildTextContent(doc: Node): string {
    const parts: string[] = []
    doc.forEach((child) => {
        if (child.isAtom || (child.content.size === 0 && !child.isTextblock)) {
            return
        }
        const text = child.textBetween(0, child.content.size, '\n', ' ')
        if (text.length > 0) {
            parts.push(text)
        }
    })
    return parts.join('\n')
}

async function editJsonNotebook(
    context: Context,
    notebookPath: string,
    notebook: Schemas.Notebook,
    params: JsonParams
): Promise<Schemas.Notebook> {
    // Find target subtree(s) and apply the replacement.
    const matches = countMatches(notebook.content, params.old_value)
    if (matches === 0) {
        const currentContentJson = safeJsonStringify(notebook.content)
        const oldValueJson = safeJsonStringify(params.old_value)
        const nodeCount = topLevelNodeCount(notebook.content)
        throw new Error(
            'old_value was not found in the notebook content. ' +
                'Matching compares every key, value, and array index — extra or missing fields will ' +
                'prevent a match. Common causes: an explicit `attrs: null` vs. omitted attrs; content ' +
                'has changed since you last read it (call `notebooks-retrieve` to refresh); or you ' +
                'passed only part of the value where the full one is stored. ' +
                `Current notebook JSON length: ${currentContentJson.length} characters. ` +
                `Top-level node count: ${nodeCount ?? 'unknown'}. ` +
                `old_value JSON length: ${oldValueJson.length} characters. ` +
                `old_value preview: ${truncateForError(oldValueJson)}.`
        )
    }

    if (matches > 1 && params.replace_all !== true) {
        throw new Error(
            `old_value matches ${matches} places in the notebook content. ` +
                'Either include more surrounding structure to make it unique (e.g. pass the parent ' +
                'paragraph instead of just a text node), or set `replace_all: true` to replace every match.'
        )
    }

    const newContent = deepReplace(notebook.content, params.old_value, params.new_value, params.replace_all === true)
    if (newContent === null || typeof newContent !== 'object' || Array.isArray(newContent)) {
        throw new Error(
            'Replacement produced a non-object root. A ProseMirror doc must be `{"type":"doc","content":[...]}` at the top level.'
        )
    }

    const rawContent = notebook.content as unknown as ProseMirrorNodeJSON
    const newContentObj = newContent as unknown as ProseMirrorNodeJSON
    const schema = buildSchemaForDoc([rawContent, newContentObj])

    const oldDoc = Node.fromJSON(schema, packDocAttrs(rawContent))
    let newDoc: Node
    try {
        newDoc = Node.fromJSON(schema, packDocAttrs(newContentObj))
    } catch (e) {
        throw new Error(
            `After applying the replacement, the notebook content does not parse as a valid ProseMirror document: ${
                e instanceof Error ? e.message : String(e)
            }. Check node \`type\` strings, attrs shapes, and that text nodes have a \`text\` field.`
        )
    }

    // Build steps via ProseMirror Transform API
    const steps = buildMinimalSteps(oldDoc, newDoc)
    if (steps.length === 0) {
        return notebook
    }

    // POST to collab/save. Non-2xx responses are thrown as PostHogApiError by `request()`.
    const unpackedContent = unpackDocAttrs(newDoc.toJSON() as ProseMirrorNodeJSON)
    return await context.api.request<Schemas.Notebook>({
        method: 'POST',
        path: `${notebookPath}collab/save/`,
        body: {
            client_id: uuidv4(),
            version: notebook.version,
            steps: steps.map((s) => s.toJSON()),
            content: unpackedContent as unknown as Record<string, unknown>,
            text_content: buildTextContent(newDoc),
        },
    })
}

export const editHandler: ToolBase<typeof NotebookEditSchema, Schemas.Notebook>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = await context.stateManager.getProjectId()
    const notebookPath = `/api/projects/${encodeURIComponent(projectId)}/notebooks/${encodeURIComponent(params.short_id)}/`

    // Load current notebook.
    const notebook = await context.api.request<Schemas.Notebook>({ method: 'GET', path: notebookPath })

    if (notebook.content === null || typeof notebook.content !== 'object' || Array.isArray(notebook.content)) {
        throw new Error(
            `Notebook ${params.short_id} has no editable content. ` +
                'Create one with `notebooks-create` or initialise its content first.'
        )
    }

    if (typeof notebook.version !== 'number') {
        throw new Error(`Notebook ${params.short_id} has no numeric version — required for optimistic concurrency.`)
    }

    if (isMarkdownParams(params)) {
        return await editMarkdownNotebook(context, notebookPath, notebook, params)
    }

    return await editJsonNotebook(context, notebookPath, notebook, params)
}

const tool = (): ToolBase<typeof NotebookEditSchema, Schemas.Notebook> => ({
    name: 'notebook-edit',
    schema: NotebookEditSchema,
    handler: editHandler,
})

export default tool
