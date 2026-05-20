/**
 * Rebase a list of pending steps over a list of steps that landed on the
 * server while we were building ours.
 *
 * This is the same primitive that `prosemirror-collab`'s `receiveTransaction`
 * uses internally — we just call `prosemirror-transform.Mapping` directly so
 * we don't need to instantiate an `EditorState`/`Plugin` in the worker.
 *
 * Algorithm:
 *   1. Start with `oldDoc` at server version `V`.
 *   2. For each missed step `m_i` arriving from the server, apply it to the
 *      running doc and append its step map to a `Mapping`.
 *   3. For each pending step `p_j` we built locally, call `p_j.map(mapping)`.
 *      That returns a new step adjusted for the positions of the post-missed
 *      doc, or `null` if the position the step targeted no longer exists
 *      (e.g. the missed steps deleted everything it referred to).
 *   4. Apply each rebased step in turn. If a step's `apply` fails after
 *      mapping, the rebase is unresolvable — surface that to the agent.
 *
 * On success we return:
 *   - `steps`: rebased Step instances we can serialize and re-POST.
 *   - `finalDoc`: the document the server-side will have after applying our
 *     rebased steps on top of the current head.
 *   - `version`: server version after the missed steps (we POST with this).
 */
import { type Node as PMNode, type Schema } from 'prosemirror-model'
import { Mapping, Step } from 'prosemirror-transform'

export interface RebaseOk {
    ok: true
    steps: Step[]
    finalDoc: PMNode
    version: number
}

export interface RebaseErr {
    ok: false
    code: 'step_dropped' | 'apply_failed' | 'invalid_missed_step'
    message: string
    details?: Record<string, unknown>
}

export type RebaseResult = RebaseOk | RebaseErr

export interface MissedStepJson {
    /** Raw PM step JSON the server returned in the 409 body. */
    step: Record<string, unknown>
}

/**
 * Apply a Step to a doc and surface failures explicitly. PM's `step.apply`
 * returns `{doc, failed}` — we lift the failure into an Either so callers can
 * distinguish "could not apply" from "applied to a doc that doesn't typecheck".
 */
function tryApply(step: Step, doc: PMNode): { ok: true; doc: PMNode } | { ok: false; reason: string } {
    const result = step.apply(doc)
    if (result.failed || !result.doc) {
        return { ok: false, reason: result.failed ?? 'unknown' }
    }
    return { ok: true, doc: result.doc }
}

export function rebaseSteps(
    pendingSteps: Step[],
    missedStepsJson: MissedStepJson[],
    oldDoc: PMNode,
    schema: Schema,
    serverVersion: number
): RebaseResult {
    let doc = oldDoc
    const mapping = new Mapping()

    for (let i = 0; i < missedStepsJson.length; i++) {
        let step: Step
        try {
            step = Step.fromJSON(schema, missedStepsJson[i]!.step)
        } catch (e) {
            return {
                ok: false,
                code: 'invalid_missed_step',
                message:
                    `Could not parse missed step #${i} returned by the server: ${
                        e instanceof Error ? e.message : String(e)
                    }. ` + 'This is usually a transient schema mismatch — refetch the source document and retry.',
                details: { missed_index: i },
            }
        }
        const applied = tryApply(step, doc)
        if (!applied.ok) {
            return {
                ok: false,
                code: 'invalid_missed_step',
                message:
                    `Missed step #${i} returned by the server failed to apply locally: ${applied.reason}. ` +
                    'Refetch the source document and retry.',
                details: { missed_index: i, reason: applied.reason },
            }
        }
        doc = applied.doc
        mapping.appendMap(step.getMap())
    }

    const rebasedSteps: Step[] = []
    for (let i = 0; i < pendingSteps.length; i++) {
        const original = pendingSteps[i]!
        const mapped = original.map(mapping)
        if (!mapped) {
            return {
                ok: false,
                code: 'step_dropped',
                message:
                    `Pending step #${i} was dropped during rebase — the range it targeted was deleted by a concurrent edit. ` +
                    'Refetch the source document so you can see the new state, then re-issue your edit against it.',
                details: { dropped_index: i },
            }
        }
        const applied = tryApply(mapped, doc)
        if (!applied.ok) {
            return {
                ok: false,
                code: 'apply_failed',
                message:
                    `Pending step #${i} failed to apply after rebase: ${applied.reason}. ` +
                    'A concurrent edit changed the structure in a way that makes your edit incompatible. ' +
                    'Refetch the source document and re-issue the edit against the new state.',
                details: { failed_index: i, reason: applied.reason },
            }
        }
        rebasedSteps.push(mapped)
        doc = applied.doc

        // Extend the mapping so subsequent pending steps account for this
        // step's effect on positions too. This matches prosemirror-collab's
        // internal rebaser, which threads each rebased step's map through.
        mapping.appendMap(mapped.getMap())
    }

    return { ok: true, steps: rebasedSteps, finalDoc: doc, version: serverVersion }
}
