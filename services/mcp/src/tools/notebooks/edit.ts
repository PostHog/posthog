/**
 * `notebook-edit` tool.
 *
 * Subtree replacement against the notebook's content tree. The caller supplies
 * `{ short_id, old_value, new_value, replace_all? }` where `old_value` and
 * `new_value` are JSON values describing the subtree to find and the subtree
 * to put in its place. Match is by deep equality of the parsed values, so
 * whitespace, key order, and indentation do not matter — the agent never has
 * to imagine the tool's serialization format.
 *
 * The diff is expressed as a single ProseMirror ReplaceStep and POSTed to
 * `/collab/save` so the edit streams live to other connected clients over SSE.
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

const Subtree = z.union([z.record(z.string(), z.unknown()), z.array(z.unknown())])

export const NotebookEditSchema = z
    .object({
        short_id: z.string().describe('The notebook short_id (the public id in the URL, e.g. `aBcD1234`).'),
        old_value: Subtree.describe(
            'The piece of content to find. Copy it straight out of the response from ' +
                '`notebooks-retrieve` — typically a single node like a text node or a whole ' +
                'paragraph. Must be a JSON object or array, not a primitive. Must match exactly ' +
                'one place in the notebook unless `replace_all` is true; if it appears in more ' +
                'than one place, include more surrounding structure (e.g. pass the parent ' +
                'paragraph instead of just the text node) to make it unique. To append to the ' +
                'end of a notebook, pass the last paragraph with content — trailing empty ' +
                'paragraphs are often identical and will cause an ambiguity error.'
        ),
        new_value: Subtree.describe(
            'What to put in place of `old_value`. Pass a JSON value of the same shape — the whole ' +
                'matched piece is replaced, so include every key you want preserved. Must be a JSON ' +
                'object or array, not a primitive. Must differ from `old_value`.'
        ),
        replace_all: z
            .boolean()
            .optional()
            .describe(
                'Replace every place `old_value` matches. Default false — the tool errors out if ' +
                    '`old_value` is not unique, so you can either narrow `old_value` to a single match ' +
                    'or set `replace_all` to true.'
            ),
    })
    .refine((v) => !isDeepStrictEqual(v.old_value, v.new_value), {
        message: 'old_value and new_value must differ',
        path: ['new_value'],
    })

type Params = z.infer<typeof NotebookEditSchema>

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

    // Find target subtree(s) and apply the replacement.
    const matches = countMatches(notebook.content, params.old_value)
    if (matches === 0) {
        throw new Error(
            'old_value was not found in the notebook content. ' +
                'Matching compares every key, value, and array index — extra or missing fields will ' +
                'prevent a match. Common causes: an explicit `attrs: null` vs. omitted attrs; content ' +
                'has changed since you last read it (call `notebooks-retrieve` to refresh); or you ' +
                'passed only part of the value where the full one is stored.\n\nCurrent notebook ' +
                'content:\n' +
                JSON.stringify(notebook.content, null, 2)
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

const tool = (): ToolBase<typeof NotebookEditSchema, Schemas.Notebook> => ({
    name: 'notebook-edit',
    schema: NotebookEditSchema,
    handler: editHandler,
})

export default tool
