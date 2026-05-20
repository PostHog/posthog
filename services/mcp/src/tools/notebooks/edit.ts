/**
 * `notebook-edit` tool.
 *
 * String replacement against the notebook's content JSON, mirroring the
 * shape agents already use for code-file edits (`str_replace_editor` /
 * Cursor's edit tool):
 *
 *   {
 *     short_id: "...",
 *     old_string: "...",     // exact substring of the serialized content
 *     new_string: "...",     // replacement
 *     replace_all?: boolean  // default false; if false, old_string must
 *                            //   appear exactly once in the serialization
 *   }
 *
 * Internally the tool operates on `JSON.stringify(content, null, 2)`. The
 * agent constructs `old_string` against that pretty-printed form. After
 * applying the replacement we re-parse the JSON, compute steps via a
 * top-level block diff (so the broadcast SSE payload stays small and other
 * clients' cursors on unaffected blocks are preserved), and POST through
 * `saveWithConflictRetry` which handles refetch-on-409 and 410 stale.
 *
 * For brand-new notebooks the agent should use `notebooks-create` instead;
 * this tool requires an existing notebook with content to edit.
 */
import { Node as PMNode } from 'prosemirror-model'
import { v4 as uuidv4 } from 'uuid'
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { AnalyticsEvent } from '@/lib/analytics'
import { diffDocsToSteps } from '@/lib/prosemirror/diff'
import { buildSchemaForDoc, packDocAttrs } from '@/lib/prosemirror/schema'
import type { Context, ToolBase } from '@/tools/types'

import { type ComputedEdit, type RecomputeFailure, type RecomputeResult, saveWithConflictRetry } from './saveLoop'

/** Indentation used when serializing the notebook content for str_replace. */
export const JSON_INDENT = 2

export const NotebookEditSchema = z
    .object({
        short_id: z.string().describe('The notebook short_id (the public id in the URL, e.g. `aBcD1234`).'),
        old_string: z
            .string()
            .describe(
                'Exact text to find in the notebook content. The notebook content is serialized as ' +
                    '`JSON.stringify(notebook.content, null, 2)` — i.e. pretty-printed with a 2-space indent. ' +
                    'old_string must match a substring of that serialization exactly, including whitespace and indentation. ' +
                    'It must be unique unless replace_all is true; otherwise widen the surrounding context until exactly one match remains. ' +
                    'Call `notebooks-retrieve` first to see the current content.'
            ),
        new_string: z
            .string()
            .describe(
                'Replacement text. Must differ from old_string. May span multiple lines and may introduce or remove blocks — ' +
                    'after the replacement, the result must still be valid JSON parseable as a ProseMirror document.'
            ),
        replace_all: z
            .boolean()
            .optional()
            .describe(
                'If true, replace every occurrence of old_string. Defaults to false (exactly one match required).'
            ),
    })
    .refine((v) => v.old_string !== v.new_string, {
        message: 'old_string and new_string must differ',
        path: ['new_string'],
    })

type Params = z.infer<typeof NotebookEditSchema>

export type NotebookEditResult =
    | {
          ok: true
          isError?: false
          notebook: Schemas.Notebook
          steps_applied: number
          /** Number of times we hit 409, refetched, and re-ran str_replace before succeeding. */
          conflicts: number
          replacements: number
      }
    | {
          ok: false
          isError: true
          error:
              | RecomputeFailure
              | { code: 'stale_buffer'; message: string }
              | { code: 'conflict_exhausted'; attempts: number; message: string }
              | { code: 'no_content'; message: string }
      }

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

interface EditComputation {
    edit: ComputedEdit
    replacements: number
}

/**
 * Fetch the notebook and run the agent's str_replace against its content.
 * Used twice: once for the initial computation, and again as the `recompute`
 * callback on every 409 conflict so we re-apply the agent's intent against
 * the latest server state.
 *
 * Returns:
 *   - `{ok: true, edit, replacements}` — we have steps to POST. Steps may be
 *     empty if the str_replace produced an identical PM tree (rare, but
 *     e.g. attribute-key reordering inside the serialized JSON).
 *   - `{ok: false, error}` — the agent's intent no longer applies (target
 *     not found, ambiguous, broken JSON, broken doc). Surface as-is to the
 *     agent so it can decide what to do.
 */
async function computeEdit(
    context: Context,
    projectId: string,
    params: Params
): Promise<
    | { ok: true; computation: EditComputation }
    | { ok: false; error: RecomputeFailure | { code: 'no_content'; message: string } }
> {
    const notebook = await context.api.request<Schemas.Notebook>({
        method: 'GET',
        path: `/api/projects/${encodeURIComponent(projectId)}/notebooks/${encodeURIComponent(params.short_id)}/`,
    })

    if (
        notebook.content === undefined ||
        notebook.content === null ||
        typeof notebook.content !== 'object' ||
        Array.isArray(notebook.content)
    ) {
        return {
            ok: false,
            error: {
                code: 'no_content',
                message:
                    `Notebook ${params.short_id} has no editable content (got ${typeof notebook.content}). ` +
                    'Create the notebook with `notebooks-create` first, or initialise its content with `notebooks-partial-update`.',
            },
        }
    }

    if (typeof notebook.version !== 'number') {
        throw new Error(
            `Notebook ${params.short_id} has no numeric version (got ${typeof notebook.version}). ` +
                'The collab/save endpoint requires optimistic concurrency control — refetch the notebook and retry.'
        )
    }

    const serialized = JSON.stringify(notebook.content, null, JSON_INDENT)
    const occurrences = countOccurrences(serialized, params.old_string)

    if (occurrences === 0) {
        return {
            ok: false,
            error: {
                code: 'not_found',
                message:
                    'old_string was not found in the notebook content. ' +
                    'The notebook content is serialized with `JSON.stringify(content, null, 2)` (2-space indent). ' +
                    'Common causes: (a) the indentation in your old_string does not match (each nesting level is 2 spaces), ' +
                    '(b) the content has changed since you last read it — call `notebooks-retrieve` to refresh, ' +
                    '(c) you escaped quotes or characters that should be literal. ' +
                    'Note: keys are unquoted by JSON spec but values are; e.g. `"type": "text"`, not `type: "text"`.',
            },
        }
    }

    if (occurrences > 1 && params.replace_all !== true) {
        return {
            ok: false,
            error: {
                code: 'ambiguous',
                match_count: occurrences,
                message:
                    `old_string matches ${occurrences} places in the notebook content. ` +
                    'Either widen old_string with more surrounding JSON until it identifies exactly one location, ' +
                    'or set `replace_all: true` to replace every occurrence.',
            },
        }
    }

    const newSerialized =
        params.replace_all === true
            ? serialized.split(params.old_string).join(params.new_string)
            : serialized.replace(params.old_string, params.new_string)
    const replacements = params.replace_all === true ? occurrences : 1

    let newContent: unknown
    try {
        newContent = JSON.parse(newSerialized)
    } catch (e) {
        return {
            ok: false,
            error: {
                code: 'invalid_resulting_json',
                message:
                    'After applying the replacement, the notebook content is no longer valid JSON. ' +
                    'Check that your new_string preserves balanced braces, brackets, and quotes, and ' +
                    'that commas between fields are correct.',
                parse_error: e instanceof Error ? e.message : String(e),
            },
        }
    }

    if (newContent === null || typeof newContent !== 'object') {
        return {
            ok: false,
            error: {
                code: 'invalid_resulting_doc',
                message:
                    'After applying the replacement, the notebook content is no longer a JSON object. ' +
                    'A ProseMirror document must be `{"type":"doc","content":[...]}` at the top level.',
            },
        }
    }

    const rawContent = notebook.content as unknown as Parameters<typeof packDocAttrs>[0]
    const newContentObj = newContent as Parameters<typeof packDocAttrs>[0]
    const schema = buildSchemaForDoc([rawContent, newContentObj])

    let oldDoc: PMNode
    let newDoc: PMNode
    try {
        oldDoc = PMNode.fromJSON(schema, packDocAttrs(rawContent) as Parameters<typeof PMNode.fromJSON>[1])
    } catch (e) {
        throw new Error(
            `Failed to parse the existing notebook content into a ProseMirror document: ${
                e instanceof Error ? e.message : String(e)
            }`
        )
    }
    try {
        newDoc = PMNode.fromJSON(schema, packDocAttrs(newContentObj) as Parameters<typeof PMNode.fromJSON>[1])
    } catch (e) {
        return {
            ok: false,
            error: {
                code: 'invalid_resulting_doc',
                message:
                    'After applying the replacement, the notebook content does not parse as a valid ProseMirror document: ' +
                    (e instanceof Error ? e.message : String(e)) +
                    '. Check that node `type` strings are correct, attrs match expected shape, and text nodes carry a `text` field.',
            },
        }
    }

    const diff = diffDocsToSteps(oldDoc, newDoc)
    if (!diff.ok) {
        return { ok: false, error: { code: diff.code, message: diff.message } }
    }

    return {
        ok: true,
        computation: {
            edit: {
                steps: diff.steps,
                newDoc,
                version: notebook.version,
            },
            replacements,
        },
    }
}

export const editHandler: ToolBase<typeof NotebookEditSchema, NotebookEditResult>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    const initial = await computeEdit(context, projectId, params)
    if (!initial.ok) {
        if (initial.error.code === 'no_content') {
            return { ok: false, isError: true, error: initial.error }
        }
        return { ok: false, isError: true, error: initial.error as RecomputeFailure }
    }

    let replacements = initial.computation.replacements

    if (initial.computation.edit.steps.length === 0) {
        // The str_replace produced an identical PM tree (e.g. the agent edited
        // whitespace inside an attrs object that round-trips the same). Treat
        // as a no-op so the agent gets a clear signal that nothing changed.
        const notebook = await context.api.request<Schemas.Notebook>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(projectId)}/notebooks/${encodeURIComponent(params.short_id)}/`,
        })
        return { ok: true, notebook, steps_applied: 0, conflicts: 0, replacements }
    }

    const recompute = async (): Promise<RecomputeResult> => {
        const recomputed = await computeEdit(context, projectId, params)
        if (!recomputed.ok) {
            return { ok: false, error: recomputed.error as RecomputeFailure }
        }
        // Track how many physical replacements landed in the final attempt
        // so the agent gets an accurate count when replace_all=true and the
        // post-conflict match count differs from the original.
        replacements = recomputed.computation.replacements
        return { ok: true, edit: recomputed.computation.edit }
    }

    const result = await saveWithConflictRetry({
        context,
        projectId,
        shortId: params.short_id,
        clientId: uuidv4(),
        initial: initial.computation.edit,
        recompute,
    })

    if (!result.ok) {
        return { ok: false, isError: true, error: result.error }
    }

    void context.trackEvent(AnalyticsEvent.MCP_TOOL_CALL, {
        tool: 'notebook-edit',
        steps_count: result.steps_applied,
        conflicts: result.conflicts,
        replacements,
    })

    return {
        ok: true,
        notebook: result.notebook,
        steps_applied: result.steps_applied,
        conflicts: result.conflicts,
        replacements,
    }
}

const tool = (): ToolBase<typeof NotebookEditSchema, NotebookEditResult> => ({
    name: 'notebook-edit',
    schema: NotebookEditSchema,
    handler: editHandler,
})

export default tool
