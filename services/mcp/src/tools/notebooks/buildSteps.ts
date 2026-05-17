/**
 * Convert a parsed patch into a sequence of `ReplaceStep`s against a notebook
 * doc, and produce the resulting document.
 *
 * Hunk → step strategy:
 *   - Locate the hunk's "before" (context + removed) in the rendered line view.
 *   - Compute the PM range covering the matched block run.
 *   - Build a new content slice from the hunk's "after" (context + added)
 *     lines. Context lines reuse the original PM node so unchanged blocks
 *     preserve their full structure (custom attrs, marks, atomic widgets).
 *     Added lines become fresh paragraphs containing the line text.
 *   - Emit a single `ReplaceStep(pmFrom, pmTo, slice)` per hunk.
 *
 * We re-render after each hunk so subsequent hunks see updated positions. This
 * also means later hunks must be expressed against the doc *as edited by prior
 * hunks in the same patch* — not against the original.
 */
import { Fragment, type Node as PMNode, type Schema, Slice } from 'prosemirror-model'
import { ReplaceStep, Step } from 'prosemirror-transform'

import { type Hunk, type ParsedPatch, hunkBefore } from './patch'
import { isAtomicPlaceholderLine, locateBefore, renderDoc } from './textRender'

export type BuildErrorCode = 'anchor_not_found' | 'anchor_ambiguous' | 'cannot_construct_atomic' | 'invalid_step'

export interface BuildError {
    code: BuildErrorCode
    message: string
    /** Index of the offending hunk (0-based) for the agent to correlate with its input. */
    hunkIndex: number
    /** Optional details we surface in the error response. */
    details?: Record<string, unknown>
}

export interface BuildOk {
    ok: true
    steps: Step[]
    newDoc: PMNode
}

export interface BuildErr {
    ok: false
    error: BuildError
}

export type BuildResult = BuildOk | BuildErr

const PARAGRAPH_NODE_NAME = 'paragraph'

function buildParagraphNode(schema: Schema, text: string): PMNode {
    const paragraphType = schema.nodes[PARAGRAPH_NODE_NAME]
    if (!paragraphType) {
        // Should never happen for any real notebook since every doc we've
        // seen contains at least one paragraph; we'd discover it during
        // schema build. The fallback is to use any text-accepting block we
        // can find — but we always have paragraph in practice.
        throw new Error(
            "Notebook doc has no 'paragraph' node type. Cannot synthesize added lines without a known textblock type."
        )
    }
    const content = text.length > 0 ? Fragment.from(schema.text(text)) : Fragment.empty
    return paragraphType.create(null, content)
}

/**
 * Build the replacement Fragment for a hunk: walk the hunk's lines and for
 * each "context" or "add" line decide which PM node to emit.
 *
 *   - context line: reuse the corresponding original block (we know its
 *     index because context lines are consumed in order alongside removed
 *     lines from the matched range).
 *   - add line: construct a paragraph node.
 *
 * Returns null when the hunk asks to construct an atomic placeholder via "+",
 * which we can't honour without notebook-specific knowledge.
 */
function buildReplacementFragment(
    hunk: Hunk,
    matchedBlocks: PMNode[],
    schema: Schema
): { ok: true; fragment: Fragment } | { ok: false; code: 'cannot_construct_atomic'; line: string } {
    const nodes: PMNode[] = []
    let contextCursor = 0
    for (const line of hunk.lines) {
        if (line.kind === 'remove') {
            contextCursor++
            continue
        }
        if (line.kind === 'context') {
            // Re-use the original block to preserve every attribute / mark /
            // child structure we can't reconstruct from plain text.
            const original = matchedBlocks[contextCursor]
            if (!original) {
                // Defensive: locator returned ok so this should never happen.
                throw new Error(`Hunk context cursor out of bounds: ${contextCursor} of ${matchedBlocks.length}`)
            }
            nodes.push(original)
            contextCursor++
            continue
        }
        if (line.kind === 'add') {
            if (isAtomicPlaceholderLine(line.text)) {
                return { ok: false, code: 'cannot_construct_atomic', line: line.text }
            }
            nodes.push(buildParagraphNode(schema, line.text))
        }
    }
    return { ok: true, fragment: Fragment.fromArray(nodes) }
}

export function buildSteps(originalDoc: PMNode, patch: ParsedPatch, schema: Schema): BuildResult {
    const steps: Step[] = []
    let doc = originalDoc

    for (let hunkIndex = 0; hunkIndex < patch.hunks.length; hunkIndex++) {
        const hunk = patch.hunks[hunkIndex]!
        const rendered = renderDoc(doc)
        const before = hunkBefore(hunk)

        // A hunk containing only context lines is a no-op assertion (the agent
        // is anchoring without changing anything). Skip without emitting a
        // ReplaceStep so we don't generate noisy 0-effect collab events.
        const hasMutation = hunk.lines.some((l) => l.kind !== 'context')
        if (!hasMutation) {
            continue
        }

        const located = locateBefore(rendered, before)
        if (!located.ok) {
            if (located.code === 'not_found') {
                return {
                    ok: false,
                    error: {
                        code: 'anchor_not_found',
                        hunkIndex,
                        message:
                            `Hunk #${hunkIndex} did not match anywhere in the notebook. First missing line: ` +
                            JSON.stringify(located.firstMissingLine) +
                            '. Re-fetch the notebook with `notebooks-retrieve` to see the current content, ' +
                            'then re-issue the patch. Each hunk line must match a complete block (one block per line).',
                        details: { first_missing_line: located.firstMissingLine },
                    },
                }
            }
            return {
                ok: false,
                error: {
                    code: 'anchor_ambiguous',
                    hunkIndex,
                    message:
                        `Hunk #${hunkIndex} matched ${located.matchCount} places in the notebook. ` +
                        'Widen the surrounding context so exactly one location matches.',
                    details: { match_count: located.matchCount },
                },
            }
        }

        const startBlockIndex = located.startIndex
        const matchedBlocks =
            before.length === 0 ? [] : rendered.blocks.slice(startBlockIndex, startBlockIndex + before.length)
        const pmFrom = matchedBlocks.length > 0 ? matchedBlocks[0]!.pmStart : doc.content.size
        const pmTo = matchedBlocks.length > 0 ? matchedBlocks[matchedBlocks.length - 1]!.pmEnd : doc.content.size

        const original = matchedBlocks.map((b) => b.node)
        const replacement = buildReplacementFragment(hunk, original, schema)
        if (!replacement.ok) {
            return {
                ok: false,
                error: {
                    code: 'cannot_construct_atomic',
                    hunkIndex,
                    message:
                        `Hunk #${hunkIndex} tries to add an atomic block placeholder line ${JSON.stringify(
                            replacement.line
                        )} via "+". Atomic widgets (custom PostHog blocks like recordings, queries, or images) ` +
                        'cannot be created from plain text — they must already exist in the notebook. ' +
                        'You can keep them as context lines or remove them with "-", but not add new ones.',
                    details: { line: replacement.line },
                },
            }
        }

        // ReplaceStep over (pmFrom..pmTo) replaces the whole range. Since we
        // operate on whole-block boundaries (pmStart..pmEnd of complete
        // children), `openStart`/`openEnd` are zero — the slice is a closed
        // block sequence.
        const slice = new Slice(replacement.fragment, 0, 0)
        const step = new ReplaceStep(pmFrom, pmTo, slice)
        const applied = step.apply(doc)
        if (applied.failed || !applied.doc) {
            return {
                ok: false,
                error: {
                    code: 'invalid_step',
                    hunkIndex,
                    message:
                        `Hunk #${hunkIndex} produced a step that failed to apply: ${applied.failed ?? 'unknown error'}. ` +
                        'This usually means the hunk produced an invalid block structure (e.g. removed every block, ' +
                        'leaving the doc empty when at least one block is required). Re-fetch the notebook and adjust the patch.',
                    details: { reason: applied.failed ?? null },
                },
            }
        }

        steps.push(step)
        doc = applied.doc
    }

    return { ok: true, steps, newDoc: doc }
}
