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
import { Node as PMNode } from 'prosemirror-model'
import { Transform } from 'prosemirror-transform'
import { v4 as uuidv4 } from 'uuid'
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { buildSchemaForDoc, packDocAttrs, unpackDocAttrs } from '@/lib/prosemirror/schema'
import type { Context, ToolBase } from '@/tools/types'

export const NotebookEditSchema = z
    .object({
        short_id: z.string().describe('The notebook short_id (the public id in the URL, e.g. `aBcD1234`).'),
        old_value: z
            .unknown()
            .describe(
                'The piece of content to find. Copy it straight out of the response from ' +
                    '`notebooks-retrieve` — typically a single node like a text node or a whole ' +
                    'paragraph. Must match exactly one place in the notebook unless `replace_all` ' +
                    'is true; if it appears in more than one place, include more surrounding ' +
                    'structure (e.g. pass the parent paragraph instead of just the text node) to ' +
                    'make it unique.'
            ),
        new_value: z
            .unknown()
            .describe(
                'What to put in place of `old_value`. Pass a JSON value of the same shape — the whole ' +
                    'matched piece is replaced, so include every key you want preserved. Must differ ' +
                    'from `old_value`.'
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

/**
 * Counts subtrees within `tree` that deep-equal `target`. Stops descending into
 * a matched subtree (so a target that itself contains the same target nested
 * inside isn't double-counted), matching the replace semantics below.
 */
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
 * Walks `tree` and replaces every subtree that deep-equals `target` with a
 * fresh structured clone of `replacement`. When `replaceAll` is false, only
 * the first match is replaced; subsequent matches are left untouched.
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
 * Plain-text view for the search index. Mirrors what the frontend's
 * `editor.getText()` produces.
 */
function buildTextContent(doc: PMNode): string {
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

    if (
        notebook.content === undefined ||
        notebook.content === null ||
        typeof notebook.content !== 'object' ||
        Array.isArray(notebook.content)
    ) {
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

    // Parse old + new into ProseMirror.
    const rawContent = notebook.content as unknown as Parameters<typeof packDocAttrs>[0]
    const newContentObj = newContent as unknown as Parameters<typeof packDocAttrs>[0]
    const schema = buildSchemaForDoc([rawContent, newContentObj])

    const oldDoc = PMNode.fromJSON(schema, packDocAttrs(rawContent) as Parameters<typeof PMNode.fromJSON>[1])
    let newDoc: PMNode
    try {
        newDoc = PMNode.fromJSON(schema, packDocAttrs(newContentObj) as Parameters<typeof PMNode.fromJSON>[1])
    } catch (e) {
        throw new Error(
            `After applying the replacement, the notebook content does not parse as a valid ProseMirror document: ${
                e instanceof Error ? e.message : String(e)
            }. Check node \`type\` strings, attrs shapes, and that text nodes have a \`text\` field.`
        )
    }

    // Build steps via ProseMirror's canonical Transform API. Empty steps means
    // the deep-replace round-tripped to an identical ProseMirror tree (e.g.
    // attrs key order changed but the parsed result is structurally equal).
    const steps = oldDoc.eq(newDoc)
        ? []
        : new Transform(oldDoc).replaceWith(0, oldDoc.content.size, newDoc.content).steps
    if (steps.length === 0) {
        return notebook
    }

    // POST to collab/save. Non-2xx responses are thrown as PostHogApiError by `request()`.
    const unpackedContent = unpackDocAttrs(newDoc.toJSON() as Parameters<typeof unpackDocAttrs>[0])
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
