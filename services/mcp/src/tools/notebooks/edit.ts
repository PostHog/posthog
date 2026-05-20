/**
 * `notebook-edit` tool.
 *
 * Substring-replacement editor against the notebook's content JSON. The
 * caller supplies `{ short_id, old_string, new_string, replace_all? }`; the
 * tool finds `old_string` in the notebook's serialized content and replaces
 * it with `new_string`. The chosen serialization is
 * `JSON.stringify(content, null, 2)` (2-space indent), so callers can match
 * against pretty-printed JSON keys, attribute values, and inline text.
 *
 * Pipeline:
 *   1. GET notebook → current content + version
 *   2. Serialize content with 2-space indent, run the substring replacement,
 *      and parse the result back to JSON
 *   3. Parse old and new content into ProseMirror via a dynamic schema
 *      covering both documents
 *   4. Build one ReplaceStep via Transform.replaceWith — PM's idiomatic way
 *      to express "make this doc become that one"
 *   5. POST to /collab/save so the edit streams live to other connected
 *      clients over SSE
 *
 * Server errors (409 concurrent edit, 410 stale buffer, etc.) flow through
 * `context.api.request` → PostHogApiError → `handleToolError`, which surfaces
 * the URL, status, and Django response body verbatim to the agent. The
 * 409 body already includes the latest version + rebased steps from the
 * server, which the agent can use to retry without an extra read.
 */
import { Node as PMNode } from 'prosemirror-model'
import { Transform } from 'prosemirror-transform'
import { v4 as uuidv4 } from 'uuid'
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { buildSchemaForDoc, packDocAttrs, unpackDocAttrs } from '@/lib/prosemirror/schema'
import type { Context, ToolBase } from '@/tools/types'

/**
 * Indent (in spaces) used when serializing the notebook content before the
 * substring replacement. Exposed so tests can assert that the description
 * shown to the agent matches what the tool actually serializes.
 */
export const JSON_INDENT = 2

export const NotebookEditSchema = z
    .object({
        short_id: z.string().describe('The notebook short_id (the public id in the URL, e.g. `aBcD1234`).'),
        old_string: z
            .string()
            .describe(
                'Exact text to find in the notebook content. The notebook content is serialized as ' +
                    '`JSON.stringify(notebook.content, null, 2)` (2-space indent). ' +
                    'old_string must match a substring exactly, including whitespace and indentation. ' +
                    'Must be unique unless replace_all is true; widen surrounding context to disambiguate. ' +
                    'Call `notebooks-retrieve` first to see the current content.'
            ),
        new_string: z.string().describe('Replacement text. Must differ from old_string.'),
        replace_all: z
            .boolean()
            .optional()
            .describe('Replace every occurrence. Default false (requires unique match).'),
    })
    .refine((v) => v.old_string !== v.new_string, {
        message: 'old_string and new_string must differ',
        path: ['new_string'],
    })

type Params = z.infer<typeof NotebookEditSchema>

function countOccurrences(haystack: string, needle: string): number {
    if (needle.length === 0) {
        return 0
    }
    let count = 0
    let i = 0
    while ((i = haystack.indexOf(needle, i)) !== -1) {
        count++
        i += needle.length
    }
    return count
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

    // 1. Load current notebook.
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

    // 2. Serialize the content and apply the substring replacement.
    const serialized = JSON.stringify(notebook.content, null, JSON_INDENT)
    const occurrences = countOccurrences(serialized, params.old_string)

    if (occurrences === 0) {
        throw new Error(
            'old_string was not found in the notebook content. ' +
                'The content is serialized with `JSON.stringify(content, null, 2)` (2-space indent). ' +
                'Common causes: indentation does not match (each nesting level is 2 spaces); ' +
                'content has changed since you last read it (call `notebooks-retrieve` to refresh); ' +
                'or quoting/escaping mismatch in old_string.'
        )
    }

    if (occurrences > 1 && params.replace_all !== true) {
        throw new Error(
            `old_string matches ${occurrences} places. ` +
                'Either widen old_string with surrounding context until exactly one location matches, ' +
                'or set `replace_all: true`.'
        )
    }

    const newSerialized =
        params.replace_all === true
            ? serialized.split(params.old_string).join(params.new_string)
            : serialized.replace(params.old_string, params.new_string)

    let newContent: unknown
    try {
        newContent = JSON.parse(newSerialized)
    } catch (e) {
        throw new Error(
            `After applying the replacement, the notebook content is no longer valid JSON: ${
                e instanceof Error ? e.message : String(e)
            }. Check balanced braces, brackets, and quotes.`
        )
    }
    if (newContent === null || typeof newContent !== 'object') {
        throw new Error(
            'Replacement result is not a JSON object. A ProseMirror doc must be `{"type":"doc","content":[...]}` at the top level.'
        )
    }

    // 3. Parse old + new into PM.
    const rawContent = notebook.content as unknown as Parameters<typeof packDocAttrs>[0]
    const newContentObj = newContent as Parameters<typeof packDocAttrs>[0]
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

    // 4. Build steps via PM's canonical Transform API. Empty steps means the
    //    str_replace round-tripped to an identical PM tree (e.g. whitespace
    //    inside an attrs object that serializes back the same).
    const steps = oldDoc.eq(newDoc)
        ? []
        : new Transform(oldDoc).replaceWith(0, oldDoc.content.size, newDoc.content).steps.slice()
    if (steps.length === 0) {
        return notebook
    }

    // 5. POST to collab/save. Non-2xx responses (including 409 concurrent
    //    edit and 410 stale buffer) are thrown as PostHogApiError by
    //    `request()` and surfaced verbatim by `handleToolError` — the agent
    //    sees the URL, status, and the Django response body (which for 409
    //    already includes the latest version + rebased steps).
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
