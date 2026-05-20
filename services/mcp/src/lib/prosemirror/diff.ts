/**
 * Compute the minimal set of top-level `ReplaceStep`s that transforms
 * `oldDoc` into `newDoc`.
 *
 * Strategy: a doc is a sequence of top-level block children. We find the
 * longest common prefix and longest common suffix by deep JSON equality,
 * then the differing middle range becomes one `ReplaceStep` swapping the
 * old middle for the new middle. For a typical str_replace edit that only
 * touches the text inside one paragraph, this is exactly one step covering
 * exactly that paragraph — which keeps cursors and presence stable for
 * every other collaborator on every other block.
 *
 * Why not run our edits as one big top-level ReplaceStep over the whole
 * doc? It would work, but mapping presence/selection for other clients
 * gets clobbered (their caret maps to position 0), and the SSE broadcast
 * payload bloats unnecessarily.
 */
import { Fragment, type Node as PMNode, Slice } from 'prosemirror-model'
import { ReplaceStep, type Step } from 'prosemirror-transform'

function deepEqualJson(a: unknown, b: unknown): boolean {
    if (a === b) {
        return true
    }
    if (typeof a !== typeof b) {
        return false
    }
    if (a === null || b === null) {
        return false
    }
    if (Array.isArray(a)) {
        if (!Array.isArray(b) || a.length !== b.length) {
            return false
        }
        for (let i = 0; i < a.length; i++) {
            if (!deepEqualJson(a[i], b[i])) {
                return false
            }
        }
        return true
    }
    if (typeof a === 'object' && typeof b === 'object') {
        const ka = Object.keys(a as Record<string, unknown>)
        const kb = Object.keys(b as Record<string, unknown>)
        if (ka.length !== kb.length) {
            return false
        }
        for (const k of ka) {
            if (!deepEqualJson((a as Record<string, unknown>)[k], (b as Record<string, unknown>)[k])) {
                return false
            }
        }
        return true
    }
    return false
}

function childAt(doc: PMNode, i: number): PMNode {
    const child = doc.maybeChild(i)
    if (!child) {
        throw new Error(`child index out of bounds: ${i} of ${doc.childCount}`)
    }
    return child
}

export interface DiffOk {
    ok: true
    steps: Step[]
}

export interface DiffErr {
    ok: false
    code: 'apply_failed'
    message: string
}

export function diffDocsToSteps(oldDoc: PMNode, newDoc: PMNode): DiffOk | DiffErr {
    const oldCount = oldDoc.childCount
    const newCount = newDoc.childCount

    // Longest common prefix.
    let prefix = 0
    const maxPrefix = Math.min(oldCount, newCount)
    while (prefix < maxPrefix && deepEqualJson(childAt(oldDoc, prefix).toJSON(), childAt(newDoc, prefix).toJSON())) {
        prefix++
    }

    // Longest common suffix that doesn't overlap the prefix.
    let suffix = 0
    while (
        prefix + suffix < oldCount &&
        prefix + suffix < newCount &&
        deepEqualJson(childAt(oldDoc, oldCount - 1 - suffix).toJSON(), childAt(newDoc, newCount - 1 - suffix).toJSON())
    ) {
        suffix++
    }

    if (prefix === oldCount && oldCount === newCount && suffix === 0) {
        // The two docs are identical at the top level.
        return { ok: true, steps: [] }
    }

    // PM positions for the replacement range.
    let pmFrom = 0
    for (let i = 0; i < prefix; i++) {
        pmFrom += childAt(oldDoc, i).nodeSize
    }
    let pmTo = oldDoc.content.size
    for (let i = 0; i < suffix; i++) {
        pmTo -= childAt(oldDoc, oldCount - 1 - i).nodeSize
    }

    const newMiddle: PMNode[] = []
    for (let i = prefix; i < newCount - suffix; i++) {
        newMiddle.push(childAt(newDoc, i))
    }
    const slice = new Slice(Fragment.fromArray(newMiddle), 0, 0)

    const step = new ReplaceStep(pmFrom, pmTo, slice)
    const applied = step.apply(oldDoc)
    if (applied.failed || !applied.doc) {
        return {
            ok: false,
            code: 'apply_failed',
            message:
                `Computed ReplaceStep failed to apply: ${applied.failed ?? 'unknown'}. ` +
                'This usually means the edit produced an invalid block structure. ' +
                'Re-check that the resulting document still has at least one block.',
        }
    }
    return { ok: true, steps: [step] }
}
