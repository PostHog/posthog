/**
 * `notebook-edit` tool.
 *
 * String replacement against the notebook's content JSON, same shape as
 * code-file edit tools (str_replace_editor / Cursor's edit tool):
 *
 *   { short_id, old_string, new_string, replace_all? }
 *
 * Pipeline:
 *   1. GET notebook → current content + version
 *   2. JSON.stringify(content, null, 2) → run str_replace → JSON.parse
 *   3. Parse old + new content into PM via a dynamic schema covering both
 *   4. Build one ReplaceStep via Transform.replaceWith — PM's idiomatic way
 *      to express "make this doc become that one"
 *   5. POST to /collab/save so the edit streams live to other connected
 *      clients over SSE
 *
 * On 409 (concurrent edit) we refetch and surface the latest content in the
 * error so the agent can re-apply without an extra read. Auto-retry/rebase
 * lands in a follow-up PR.
 */
import { Node as PMNode } from 'prosemirror-model'
import { Transform } from 'prosemirror-transform'
import { v4 as uuidv4 } from 'uuid'
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { buildSchemaForDoc, packDocAttrs, unpackDocAttrs } from '@/lib/prosemirror/schema'
import type { Context, ToolBase } from '@/tools/types'

/** Indentation used when serializing the notebook content for str_replace. */
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

    // 2. Serialize + str_replace.
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

    // 5. POST to collab/save. ApiClient.requestRaw already throws on 401 and
    //    PostHogPermissionError on 403 — auth/scope errors get nicely
    //    formatted by handleToolError without us doing anything special.
    const unpackedContent = unpackDocAttrs(newDoc.toJSON() as Parameters<typeof unpackDocAttrs>[0])
    const result = await context.api.requestRaw({
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

    if (result.status === 200) {
        return result.body as Schemas.Notebook
    }

    if (result.status === 409) {
        // Concurrent edit landed between our GET and our POST. Refetch and
        // surface the latest content in the error so the agent can re-apply
        // its edit against fresh state without an extra read tool call.
        const fresh = await context.api.request<Schemas.Notebook>({ method: 'GET', path: notebookPath })
        throw new Error(
            'The notebook was modified by someone else between when you loaded it and when you tried to save. ' +
                'Re-apply your edit against the latest version below.\n\n' +
                `Latest version: ${fresh.version}\n` +
                `Latest content:\n${JSON.stringify(fresh.content, null, JSON_INDENT)}`
        )
    }

    if (result.status === 410) {
        throw new Error(
            'The notebook has been edited extensively since you loaded it, and the server can no longer ' +
                'compute a clean conflict resolution. ' +
                'Call `notebooks-retrieve` to get the latest version, then re-apply your edit.'
        )
    }

    const bodyText = typeof result.body === 'string' ? result.body : JSON.stringify(result.body)
    throw new Error(`collab/save returned unexpected status ${result.status}: ${bodyText}`)
}

const tool = (): ToolBase<typeof NotebookEditSchema, Schemas.Notebook> => ({
    name: 'notebook-edit',
    schema: NotebookEditSchema,
    handler: editHandler,
})

export default tool
