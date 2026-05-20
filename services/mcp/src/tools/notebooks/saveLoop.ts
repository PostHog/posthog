/**
 * Shared "POST collab/save with refetch-on-conflict" pipeline for notebook
 * editing tools.
 *
 * Why refetch instead of rebase:
 *   `prosemirror-collab`'s rebase machinery (`receiveTransaction`, the
 *   internal `rebaseSteps`) is designed for interactive editors with a
 *   long-lived `EditorState` carrying unconfirmed in-flight steps. It
 *   preserves those specific steps across concurrent changes — the right
 *   model for a user typing characters. Our MCP tools are one-shot: the
 *   agent provides a semantic intent (e.g. "replace this exact string"),
 *   not a sequence of operations. The honest behaviour on a 409 is to
 *   recompute that intent against the new state — if the intent still
 *   applies, we resend; if it doesn't (e.g. the target string was deleted),
 *   we surface a structured error so the agent can decide what to do.
 *
 *   Tiptap's own docs make the same distinction: their server-side PATCH
 *   endpoint for "non-interactive clients" deliberately doesn't run the
 *   collab rebase dance either.
 *
 * Server interaction:
 *   POST → 200 done.
 *   POST → 410 stale_buffer (server's Redis stream was trimmed; the
 *           caller's `version` is too far behind to even be expressed as a
 *           conflict).
 *   POST → 409 conflict (concurrent edit). We refetch via the caller's
 *           `recompute` callback (which re-runs the agent's intent against
 *           the new state) and try again. Capped retries.
 */
import { type Node as PMNode } from 'prosemirror-model'
import type { Step } from 'prosemirror-transform'

import type { Schemas } from '@/api/generated'
import { unpackDocAttrs } from '@/lib/prosemirror/schema'
import type { Context } from '@/tools/types'

export const MAX_CONFLICT_RETRIES = 3

export interface SaveOk {
    ok: true
    notebook: Schemas.Notebook
    steps_applied: number
    /** Number of times we hit 409 and refetched + recomputed before succeeding. */
    conflicts: number
}

export interface SaveErr {
    ok: false
    error:
        | { code: 'stale_buffer'; message: string }
        | { code: 'conflict_exhausted'; attempts: number; message: string }
        | RecomputeFailure
}

export type SaveResult = SaveOk | SaveErr

/**
 * Caller-provided shape: a structured failure that the recompute callback
 * can surface after re-running the agent's intent against fresh state
 * (e.g. "the string I was supposed to replace no longer exists").
 * Marked as `isError` so the handler can return it directly.
 */
export interface RecomputeFailure {
    code: string
    message: string
    [key: string]: unknown
}

export interface ComputedEdit {
    steps: Step[]
    /** The doc the steps will produce — POSTed as `content` on collab/save. */
    newDoc: PMNode
    /** Server version the steps target (the version the agent's intent was just computed against). */
    version: number
    /** Optional title rename, threaded into the POST body. */
    title?: string | undefined
}

/**
 * Result of (re-)running the agent's intent against the current notebook
 * state. `ok: true` means we have steps to POST. `ok: false` means the
 * intent is no longer expressible — return the structured error to the
 * agent.
 */
export type RecomputeResult = { ok: true; edit: ComputedEdit } | { ok: false; error: RecomputeFailure }

/**
 * POST a collab/save once. Returns `{accepted}` / `{conflict}` / `{stale}`
 * without throwing on application-level non-2xx (auth errors still throw
 * through `ApiClient.requestRaw`'s existing 401/403 handling).
 */
async function postCollabSaveOnce(
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
): Promise<{ status: 'accepted'; notebook: Schemas.Notebook } | { status: 'conflict' } | { status: 'stale' }> {
    const result = await context.api.requestRaw({
        method: 'POST',
        path: `/api/projects/${encodeURIComponent(projectId)}/notebooks/${encodeURIComponent(shortId)}/collab/save/`,
        body: body as unknown as Record<string, unknown>,
    })

    if (result.status === 200) {
        return { status: 'accepted', notebook: result.body as Schemas.Notebook }
    }
    if (result.status === 409) {
        return { status: 'conflict' }
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
 * Render the plain-text view used by the server's search index. Mirrors
 * what the frontend's `editor.getText()` produces.
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

/**
 * POST steps to collab/save. On 409 the `recompute` callback is invoked to
 * re-run the agent's intent against fresh server state, producing a new
 * set of steps + target doc + version that we then POST.
 *
 * `recompute` is responsible for:
 *   - GET-ing the latest notebook
 *   - Re-applying the agent's intent (e.g. str_replace) to the new content
 *   - Returning the resulting steps + newDoc + version, or a structured
 *     error if the intent no longer applies (e.g. `not_found`).
 */
export async function saveWithConflictRetry(args: {
    context: Context
    projectId: string
    shortId: string
    clientId: string
    /** Initial computed edit. */
    initial: ComputedEdit
    /**
     * Called on 409 to recompute steps against the latest server state.
     * Receives no args — the callback owns the GET.
     */
    recompute: () => Promise<RecomputeResult>
}): Promise<SaveResult> {
    let current = args.initial
    let conflicts = 0

    for (let attempt = 0; attempt <= MAX_CONFLICT_RETRIES; attempt++) {
        const stepsJson = current.steps.map((s) => s.toJSON()) as unknown as Array<Record<string, unknown>>
        const unpackedContent = unpackDocAttrs(
            current.newDoc.toJSON() as unknown as Parameters<typeof unpackDocAttrs>[0]
        ) as unknown as Record<string, unknown>

        const body = {
            client_id: args.clientId,
            version: current.version,
            steps: stepsJson,
            content: unpackedContent,
            text_content: buildTextContent(current.newDoc),
            ...(current.title !== undefined ? { title: current.title } : {}),
        }

        const result = await postCollabSaveOnce(args.context, args.projectId, args.shortId, body)

        if (result.status === 'accepted') {
            return {
                ok: true,
                notebook: result.notebook,
                steps_applied: current.steps.length,
                conflicts,
            }
        }

        if (result.status === 'stale') {
            return {
                ok: false,
                error: {
                    code: 'stale_buffer',
                    message:
                        'The notebook has had many concurrent edits since you last read it, and the server has trimmed its rebase buffer. ' +
                        'Re-fetch the notebook with `notebooks-retrieve` to get the latest content + version, then re-issue your edit against the new state.',
                },
            }
        }

        // Conflict — recompute the intent against the new state and try again.
        conflicts++
        if (conflicts > MAX_CONFLICT_RETRIES) {
            break
        }
        const recomputed = await args.recompute()
        if (!recomputed.ok) {
            return { ok: false, error: recomputed.error }
        }
        if (recomputed.edit.steps.length === 0) {
            // After the concurrent edit, our intent maps to a no-op (e.g. the
            // change has already been applied by someone else). Return the
            // current notebook state — the agent's desired end state was reached.
            const refetched = await args.context.api.request<Schemas.Notebook>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(args.projectId)}/notebooks/${encodeURIComponent(args.shortId)}/`,
            })
            return {
                ok: true,
                notebook: refetched,
                steps_applied: 0,
                conflicts,
            }
        }
        current = recomputed.edit
    }

    return {
        ok: false,
        error: {
            code: 'conflict_exhausted',
            attempts: conflicts,
            message:
                `Hit ${conflicts} concurrent-edit conflicts in a row. ` +
                'The notebook is being edited heavily by another user right now. ' +
                'Re-fetch with `notebooks-retrieve` and retry once activity has settled, or split your edit into smaller changes.',
        },
    }
}
