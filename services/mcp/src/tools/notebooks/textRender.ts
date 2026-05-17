/**
 * Render a notebook PM document down to a line-per-top-level-block text view,
 * tracking the PM positions of each line so a patch hunk can be mapped back to
 * a `(from, to)` range suitable for a ReplaceStep.
 *
 * Why line-per-block:
 *   - The notebook editor saves whole blocks as the unit of meaningful change
 *     (heading, paragraph, list item, ph-* widget). A patch that targets
 *     anything finer (mid-paragraph word edits) would force us to map text
 *     offsets through marks and inline atoms, which is fragile and exactly
 *     the kind of thing that fails silently on unknown node types.
 *   - Block-granularity matches how prosemirror-collab is most commonly used
 *     in practice, and it preserves cursor/selection for other clients on
 *     unaffected blocks.
 *
 * Atomic / contentless blocks (custom ph-* widgets that have no text content)
 * render as a single placeholder line `<atom:type>`. The agent can:
 *   - Keep the line as context to anchor surrounding edits.
 *   - Remove the line (we'll delete the whole node).
 *   - It cannot edit a `<atom:type>` line in-place — the only "+" lines we
 *     synthesize are paragraphs (the only block type we can construct without
 *     hardcoding any notebook-specific knowledge).
 *
 * The empty-block convention: blocks with no text content render as the empty
 * string `""`. Agents are still free to include them as context lines.
 */
import { type Node as PMNode } from 'prosemirror-model'

export interface RenderedBlock {
    /** Index in `RenderedDoc.lines`. */
    index: number
    /** Plain-text content of the block (empty string for blank paragraphs). */
    text: string
    /** PM position immediately before this block's opening token. */
    pmStart: number
    /** PM position immediately after this block's closing token. */
    pmEnd: number
    /** Original node (kept so we can preserve it through unchanged context lines). */
    node: PMNode
    /** True if this block is an atomic leaf (no editable content). */
    isAtom: boolean
}

export interface RenderedDoc {
    lines: string[]
    blocks: RenderedBlock[]
}

const ATOM_PLACEHOLDER_PREFIX = '<atom:'
const ATOM_PLACEHOLDER_SUFFIX = '>'

function isAtomLine(line: string): boolean {
    return line.startsWith(ATOM_PLACEHOLDER_PREFIX) && line.endsWith(ATOM_PLACEHOLDER_SUFFIX)
}

function renderBlock(node: PMNode): { text: string; isAtom: boolean } {
    if (node.isAtom || (node.content.size === 0 && !node.isTextblock)) {
        return { text: `${ATOM_PLACEHOLDER_PREFIX}${node.type.name}${ATOM_PLACEHOLDER_SUFFIX}`, isAtom: true }
    }
    // textBetween walks the subtree and joins all text content, separating
    // child blocks with `\n` so multi-paragraph containers (e.g. blockquotes)
    // still render as a single line by joining on space here. We want one
    // line per top-level block; nested newlines from descendants get
    // collapsed to spaces so the line stays atomic.
    const text = node.textBetween(0, node.content.size, ' ', ' ')
    return { text, isAtom: false }
}

export function renderDoc(doc: PMNode): RenderedDoc {
    const blocks: RenderedBlock[] = []
    const lines: string[] = []

    // Top-level children of the doc node. Position math: doc itself occupies
    // positions [0, doc.content.size+1]; each direct child `node` starts at the
    // running offset and consumes `node.nodeSize` positions.
    let offset = 0
    doc.forEach((child) => {
        const pmStart = offset
        const pmEnd = offset + child.nodeSize
        const rendered = renderBlock(child)
        const index = blocks.length
        blocks.push({ index, text: rendered.text, pmStart, pmEnd, node: child, isAtom: rendered.isAtom })
        lines.push(rendered.text)
        offset = pmEnd
    })

    return { lines, blocks }
}

/**
 * Find a contiguous run of lines matching `target` in `rendered.lines`. The
 * match must be unique — if a hunk matches in multiple places the agent has
 * to disambiguate by widening its context.
 *
 * Returns the start index in `rendered.blocks` (== line index) of the first
 * matched line, or one of the structured locator errors.
 */
export type LocateOk = { ok: true; startIndex: number }
export type LocateErr =
    | { ok: false; code: 'not_found'; firstMissingLine: string }
    | { ok: false; code: 'ambiguous'; matchCount: number }

export function locateBefore(rendered: RenderedDoc, target: string[]): LocateOk | LocateErr {
    if (target.length === 0) {
        // An empty "before" means a pure-insertion hunk. Convention: place the
        // insertion at the end of the doc. The caller decides what to do — we
        // signal this with a sentinel index equal to the line count.
        return { ok: true, startIndex: rendered.lines.length }
    }
    const candidates: number[] = []
    for (let i = 0; i <= rendered.lines.length - target.length; i++) {
        let matched = true
        for (let j = 0; j < target.length; j++) {
            if (rendered.lines[i + j] !== target[j]) {
                matched = false
                break
            }
        }
        if (matched) {
            candidates.push(i)
        }
    }
    if (candidates.length === 0) {
        return { ok: false, code: 'not_found', firstMissingLine: target[0]! }
    }
    if (candidates.length > 1) {
        return { ok: false, code: 'ambiguous', matchCount: candidates.length }
    }
    return { ok: true, startIndex: candidates[0]! }
}

/**
 * True if a hunk line refers to an atomic placeholder. Used by the step
 * builder to refuse `+` operations that try to "construct" a custom widget
 * from plain text (since we have no way to do that schema-agnostically).
 */
export function isAtomicPlaceholderLine(line: string): boolean {
    return isAtomLine(line)
}
