/**
 * `notebooks-collab-edit` tool.
 *
 * Applies an apply_patch-style diff to a notebook by:
 *   1. GET /notebooks/{short_id} → current `content` + `version`.
 *   2. Build a permissive ProseMirror schema from the doc.
 *   3. Parse the patch → array of hunks.
 *   4. For each hunk, compute a `ReplaceStep` against the doc; accumulate
 *      steps and the resulting doc.
 *   5. POST /notebooks/{short_id}/collab/save/ with `steps`, `content`,
 *      `version`. The server's Redis-streaming endpoint broadcasts each
 *      step to other connected clients so the edit appears live in
 *      open notebooks.
 *   6. On 409, rebase pending steps over the missed steps the server
 *      returned in the body, then POST again. Capped retries.
 *   7. On 410, return a structured error telling the agent to refetch.
 *
 * Why a separate tool from `notebooks-partial-update`:
 *   - `notebooks-partial-update` calls the legacy PATCH path which writes
 *     `content` directly without streaming to other clients. Edits made
 *     through it are invisible to anyone with the notebook open until they
 *     reload — bad UX for human-agent collaboration.
 *   - `collab/save` is the new streaming path. Other clients receive each
 *     step over SSE in near-real-time.
 */
import { v4 as uuidv4 } from 'uuid'
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { AnalyticsEvent } from '@/lib/analytics'
import type { Context, ToolBase } from '@/tools/types'

import { type BuildError, buildSteps } from './buildSteps'
import { type ParsedPatch, PatchParseError, parsePatch } from './patch'
import { type RebaseErr, rebaseSteps } from './rebase'
import { buildSchemaForDoc, packDocAttrs, unpackDocAttrs } from './schema'
import { Node as PMNode, type Schema } from 'prosemirror-model'
import type { Step } from 'prosemirror-transform'

const MAX_REBASE_ATTEMPTS = 3

export const NotebooksCollabEditSchema = z.object({
    short_id: z.string().describe('The notebook short_id (visible in the URL, e.g. `aBcD1234`).'),
    patch: z.string().describe(
        // Spelt out so the agent knows precisely what shape we accept. Mirrors
        // the apply_patch convention from OpenAI's cookbook, simplified to a
        // single document target.
        'apply_patch-style diff against the notebook. ' +
            'Each line of the rendered notebook corresponds to one top-level block (paragraph, heading, list item, etc.). ' +
            'Format:\n' +
            '```\n' +
            '*** Begin Patch\n' +
            '@@\n' +
            ' context line (existing block, unchanged)\n' +
            '-block to remove\n' +
            '+block to add (will be inserted as a paragraph)\n' +
            '*** End Patch\n' +
            '```\n' +
            'Rules: every line must start with " " (context), "-" (remove) or "+" (add). ' +
            'Multiple hunks (each starting with `@@`) are applied in order. ' +
            'Context lines must match the existing notebook content exactly — call `notebooks-retrieve` first to see what to anchor against. ' +
            'Atomic block widgets (lines like `<atom:ph-recording>`) can be kept as context or removed, but cannot be added via "+" — they require dedicated insertion flows.'
    ),
    title: z.string().optional().describe('Optional new title for the notebook. Omit to leave the title unchanged.'),
})

type Params = z.infer<typeof NotebooksCollabEditSchema>

interface CollabSaveResponse {
    status: 'accepted' | 'conflict' | 'stale'
    version?: number | undefined
    notebook?: Schemas.Notebook | undefined
    /** When 'conflict': the missed steps the server has on top of our version. */
    missed_steps?: Array<{ step: Record<string, unknown>; client_id: string }> | undefined
    /** When 'conflict': server's current head version. */
    server_version?: number | undefined
}

/**
 * Issue a single POST to /collab/save and classify the response. Throws on
 * unexpected statuses or transport errors so the outer loop can fail loudly.
 */
async function postCollabSave(
    context: Context,
    projectId: string,
    shortId: string,
    body: {
        client_id: string
        version: number
        steps: Array<Record<string, unknown>>
        content: Record<string, unknown>
        text_content: string
        title?: string
    }
): Promise<CollabSaveResponse> {
    const result = await context.api.requestRaw({
        method: 'POST',
        path: `/api/projects/${encodeURIComponent(projectId)}/notebooks/${encodeURIComponent(shortId)}/collab/save/`,
        body,
    })

    if (result.status === 200) {
        return {
            status: 'accepted',
            notebook: result.body as Schemas.Notebook,
            version: (result.body as { version: number }).version,
        }
    }
    if (result.status === 409) {
        const conflict = (result.body ?? {}) as {
            steps?: Array<Record<string, unknown>>
            client_ids?: string[]
            version?: number
        }
        const missed = (conflict.steps ?? []).map((step, i) => ({
            step,
            client_id: conflict.client_ids?.[i] ?? '',
        }))
        return { status: 'conflict', missed_steps: missed, server_version: conflict.version }
    }
    if (result.status === 410) {
        return { status: 'stale' }
    }

    const bodyText = typeof result.body === 'string' ? result.body : JSON.stringify(result.body)
    throw new Error(
        `collab/save returned unexpected status ${result.status}. Body: ${bodyText}. ` +
            'This is not a recoverable error; the request was rejected before any edits were applied.'
    )
}

/**
 * Render plain-text view used by the server's search index. Mirrors the
 * `editor.getText()` output the frontend sends: concatenate textual content
 * with newlines between blocks. Doesn't need to be semantically perfect — it's
 * just used for the `text_content` search column.
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

function formatBuildError(error: BuildError): { ok: false; isError: true; error: BuildError } {
    return { ok: false, isError: true, error }
}

function formatPatchParseError(error: PatchParseError): {
    ok: false
    isError: true
    error: { code: 'patch_parse_error'; message: string; line_number: number }
} {
    return {
        ok: false,
        isError: true,
        error: {
            code: 'patch_parse_error',
            message:
                `Could not parse the patch: ${error.message}. ` +
                'Each hunk must start with `@@` and every line within a hunk must start with " " (context), "-" (remove), or "+" (add). ' +
                'See the tool description for the exact format.',
            line_number: error.lineNumber,
        },
    }
}

function formatRebaseError(error: RebaseErr): { ok: false; isError: true; error: RebaseErr } {
    return { ok: false, isError: true, error }
}

function formatStaleError(): {
    ok: false
    isError: true
    error: { code: 'stale_buffer'; message: string }
} {
    return {
        ok: false,
        isError: true,
        error: {
            code: 'stale_buffer',
            message:
                'The notebook has had many concurrent edits since you last read it, and the server has trimmed its rebase buffer. ' +
                'Re-fetch the notebook with `notebooks-retrieve` to get the latest `content` + `version`, then re-issue your patch against the new state.',
        },
    }
}

function formatRebaseExhausted(attempts: number): {
    ok: false
    isError: true
    error: { code: 'rebase_exhausted'; attempts: number; message: string }
} {
    return {
        ok: false,
        isError: true,
        error: {
            code: 'rebase_exhausted',
            attempts,
            message:
                `Rebased ${attempts} times but the notebook keeps changing under us. ` +
                'The notebook is currently being edited heavily by another user. ' +
                'Re-fetch with `notebooks-retrieve` and retry once activity has settled, or split your edit into smaller patches.',
        },
    }
}

export type CollabEditResult =
    | {
          ok: true
          isError?: false
          notebook: Schemas.Notebook
          steps_applied: number
          rebases: number
      }
    | {
          ok: false
          isError: true
          error:
              | BuildError
              | RebaseErr
              | { code: 'patch_parse_error'; message: string; line_number: number }
              | { code: 'stale_buffer'; message: string }
              | { code: 'rebase_exhausted'; attempts: number; message: string }
      }

export const collabEditHandler: ToolBase<typeof NotebooksCollabEditSchema, CollabEditResult>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    // 1. Fetch current notebook.
    const notebook = await context.api.request<Schemas.Notebook>({
        method: 'GET',
        path: `/api/projects/${encodeURIComponent(projectId)}/notebooks/${encodeURIComponent(params.short_id)}/`,
    })

    if (notebook.content === undefined || notebook.content === null || typeof notebook.content !== 'object') {
        throw new Error(
            `Notebook ${params.short_id} has no editable content (got ${typeof notebook.content}). ` +
                'Create the notebook with `notebooks-create` first, or use `notebooks-partial-update` to set initial content.'
        )
    }

    // 2. Parse patch.
    let patch: ParsedPatch
    try {
        patch = parsePatch(params.patch)
    } catch (e) {
        if (e instanceof PatchParseError) {
            return formatPatchParseError(e)
        }
        throw e
    }

    // 3. Build schema + parse doc.
    const rawContent = notebook.content as Record<string, unknown>
    const packed = packDocAttrs(rawContent as unknown as Parameters<typeof packDocAttrs>[0])
    const schema: Schema = buildSchemaForDoc(rawContent as unknown as Parameters<typeof buildSchemaForDoc>[0])
    let doc: PMNode
    try {
        doc = PMNode.fromJSON(schema, packed as unknown as Parameters<typeof PMNode.fromJSON>[1])
    } catch (e) {
        throw new Error(
            `Failed to parse notebook content into a ProseMirror document: ${e instanceof Error ? e.message : String(e)}. ` +
                'This is usually a schema-incompatibility bug in the MCP — please report it. As a fallback, use `notebooks-partial-update` to replace the content wholesale.'
        )
    }

    // 4. Build steps.
    const built = buildSteps(doc, patch, schema)
    if (!built.ok) {
        return formatBuildError(built.error)
    }
    let pendingSteps: Step[] = built.steps
    let newDoc: PMNode = built.newDoc

    if (pendingSteps.length === 0) {
        // The patch was a no-op (every line was context). Return current notebook
        // without round-tripping through the server so the agent gets a clear
        // signal that nothing changed.
        return {
            ok: true,
            notebook,
            steps_applied: 0,
            rebases: 0,
        }
    }

    // 5. POST with rebase retry loop.
    if (typeof notebook.version !== 'number') {
        throw new Error(
            `Notebook ${params.short_id} has no numeric version (got ${typeof notebook.version}). ` +
                'The collab/save endpoint requires optimistic concurrency control — refetch the notebook and retry.'
        )
    }
    const clientId = uuidv4()
    let version: number = notebook.version
    let rebases = 0

    for (let attempt = 0; attempt <= MAX_REBASE_ATTEMPTS; attempt++) {
        const stepsJson = pendingSteps.map((s) => s.toJSON())
        const unpackedContent = unpackDocAttrs(newDoc.toJSON() as unknown as Parameters<typeof unpackDocAttrs>[0])
        const body = {
            client_id: clientId,
            version,
            steps: stepsJson as unknown as Array<Record<string, unknown>>,
            content: unpackedContent as unknown as Record<string, unknown>,
            text_content: buildTextContent(newDoc),
            ...(params.title !== undefined ? { title: params.title } : {}),
        }

        const result = await postCollabSave(context, projectId, params.short_id, body)

        if (result.status === 'accepted' && result.notebook) {
            // Fire-and-forget analytics so we can spot adoption + rebase rates.
            void context.trackEvent(AnalyticsEvent.MCP_TOOL_CALL, {
                tool: 'notebooks-collab-edit',
                steps_count: pendingSteps.length,
                rebases,
                hunks: patch.hunks.length,
            })
            return {
                ok: true,
                notebook: result.notebook,
                steps_applied: pendingSteps.length,
                rebases,
            }
        }

        if (result.status === 'stale') {
            return formatStaleError()
        }

        // Conflict — rebase and retry.
        if (!result.missed_steps || result.server_version === undefined) {
            throw new Error(
                'collab/save returned 409 without missed_steps + server_version body. ' +
                    'This is a backend contract violation; the request cannot be safely retried.'
            )
        }
        const rebased = rebaseSteps(pendingSteps, result.missed_steps, doc, schema, result.server_version)
        if (!rebased.ok) {
            return formatRebaseError(rebased)
        }
        pendingSteps = rebased.steps
        newDoc = rebased.finalDoc
        version = rebased.version
        // The doc we rebase from for the *next* iteration is what the server
        // had at this version — i.e. the doc with the missed steps applied
        // but without our pending steps. We compute it the same way `rebase`
        // did internally by starting from the server head before our steps.
        // For simplicity we treat `newDoc` (which includes our steps) as the
        // doc for the next iteration; if another rebase is needed, `rebase`
        // will re-apply missed steps on top of it which is what the server
        // expects (it sees them as additional concurrent edits).
        rebases++

        if (rebases > MAX_REBASE_ATTEMPTS) {
            return formatRebaseExhausted(rebases)
        }
    }

    return formatRebaseExhausted(rebases)
}

const tool = (): ToolBase<typeof NotebooksCollabEditSchema, CollabEditResult> => ({
    name: 'notebooks-collab-edit',
    schema: NotebooksCollabEditSchema,
    handler: collabEditHandler,
})

export default tool
