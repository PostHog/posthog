/**
 * Shared "POST collab/save with rebase-and-retry" pipeline. Used by
 * `notebook-edit` today; kept generic so any future notebook editing tool
 * that produces PM steps + a target doc can route through it without
 * duplicating the retry semantics.
 *
 * Once steps + target doc exist, the server interaction is:
 *   - POST steps + resulting content + version
 *   - 200 → done
 *   - 409 → rebase pending steps over the missed range, retry (cap 3)
 *   - 410 → stale_buffer error
 */
import { type Node as PMNode, type Schema } from 'prosemirror-model'
import type { Step } from 'prosemirror-transform'

import type { Schemas } from '@/api/generated'
import type { Context } from '@/tools/types'

import { type RebaseErr, rebaseSteps } from '@/lib/prosemirror/rebase'
import { unpackDocAttrs } from '@/lib/prosemirror/schema'

export const MAX_REBASE_ATTEMPTS = 3

export interface SaveOk {
    ok: true
    notebook: Schemas.Notebook
    steps_applied: number
    rebases: number
}

export interface SaveErr {
    ok: false
    error:
        | RebaseErr
        | { code: 'stale_buffer'; message: string }
        | { code: 'rebase_exhausted'; attempts: number; message: string }
}

export type SaveResult = SaveOk | SaveErr

interface CollabSaveBody {
    client_id: string
    version: number
    steps: Array<Record<string, unknown>>
    content: Record<string, unknown>
    text_content: string
    title?: string
}

/**
 * Render the plain-text view used by the search index. Mirrors the
 * `editor.getText()` output the frontend sends so search results don't
 * degrade for agent edits.
 */
export function buildTextContent(doc: PMNode): string {
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

type CollabSaveOnceResult =
    | { status: 'accepted'; notebook: Schemas.Notebook }
    | {
          status: 'conflict'
          missed_steps: Array<{ step: Record<string, unknown>; client_id: string }>
          server_version: number
      }
    | { status: 'stale' }

async function postCollabSaveOnce(
    context: Context,
    projectId: string,
    shortId: string,
    body: CollabSaveBody
): Promise<CollabSaveOnceResult> {
    const result = await context.api.requestRaw({
        method: 'POST',
        path: `/api/projects/${encodeURIComponent(projectId)}/notebooks/${encodeURIComponent(shortId)}/collab/save/`,
        body: body as unknown as Record<string, unknown>,
    })

    if (result.status === 200) {
        return { status: 'accepted', notebook: result.body as Schemas.Notebook }
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
        if (conflict.version === undefined) {
            throw new Error(
                'collab/save returned 409 without a `version` field. ' +
                    'This is a backend contract violation; the request cannot be safely retried.'
            )
        }
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
 * POST a sequence of steps to collab/save, rebasing and retrying on 409 up
 * to `MAX_REBASE_ATTEMPTS` times. The caller owns building the initial
 * steps + doc; this function takes ownership only after that.
 */
export async function saveStepsWithRebase(args: {
    context: Context
    projectId: string
    shortId: string
    clientId: string
    /** Initial doc the agent's pending steps were built against (server head at version). */
    oldDoc: PMNode
    /** Schema used to deserialize any missed steps coming back in the 409 body. */
    schema: Schema
    /** Initial PM steps to POST. May be mutated through rebase iterations. */
    pendingSteps: Step[]
    /** Initial new doc after applying pendingSteps to oldDoc. */
    newDoc: PMNode
    /** Server version the initial pending steps target. */
    version: number
    /** Optional title rename, threaded into the POST body. */
    title?: string | undefined
}): Promise<SaveResult> {
    let { pendingSteps, newDoc, version } = args
    let rebases = 0

    for (let attempt = 0; attempt <= MAX_REBASE_ATTEMPTS; attempt++) {
        const stepsJson = pendingSteps.map((s) => s.toJSON()) as unknown as Array<Record<string, unknown>>
        const unpackedContent = unpackDocAttrs(
            newDoc.toJSON() as unknown as Parameters<typeof unpackDocAttrs>[0]
        ) as unknown as Record<string, unknown>

        const body: CollabSaveBody = {
            client_id: args.clientId,
            version,
            steps: stepsJson,
            content: unpackedContent,
            text_content: buildTextContent(newDoc),
            ...(args.title !== undefined ? { title: args.title } : {}),
        }

        const result = await postCollabSaveOnce(args.context, args.projectId, args.shortId, body)

        if (result.status === 'accepted') {
            return {
                ok: true,
                notebook: result.notebook,
                steps_applied: pendingSteps.length,
                rebases,
            }
        }

        if (result.status === 'stale') {
            return {
                ok: false,
                error: {
                    code: 'stale_buffer',
                    message:
                        'The notebook has had many concurrent edits since you last read it, and the server has trimmed its rebase buffer. ' +
                        'Re-fetch the notebook with `notebooks-retrieve` to get the latest `content` + `version`, then re-issue your edit against the new state.',
                },
            }
        }

        // Conflict — rebase and retry.
        const rebased = rebaseSteps(pendingSteps, result.missed_steps, args.oldDoc, args.schema, result.server_version)
        if (!rebased.ok) {
            return { ok: false, error: rebased }
        }
        pendingSteps = rebased.steps
        newDoc = rebased.finalDoc
        version = rebased.version
        rebases++

        if (rebases > MAX_REBASE_ATTEMPTS) {
            break
        }
    }

    return {
        ok: false,
        error: {
            code: 'rebase_exhausted',
            attempts: rebases,
            message:
                `Rebased ${rebases} times but the notebook keeps changing under us. ` +
                'The notebook is currently being edited heavily by another user. ' +
                'Re-fetch with `notebooks-retrieve` and retry once activity has settled, or split your edit into smaller changes.',
        },
    }
}
