/**
 * Builds a permissive ProseMirror schema dynamically from a document so we
 * can parse it without maintaining a hand-rolled list of supported node and
 * mark types.
 *
 * The canonical schema for any product using TipTap/ProseMirror lives in
 * the frontend's extension config. Reproducing that schema in the MCP
 * worker would couple us to every frontend addition; instead we walk the
 * doc JSON, collect every node and mark type we encounter, and register a
 * generic spec for each. The result accepts `Node.fromJSON` for any
 * well-formed document the agent might have just fetched.
 *
 * What this schema is good for:
 *   - `Node.fromJSON(schema, content)` round-tripping the agent's input.
 *   - Constructing `ReplaceStep` / `Slice` against block-shaped content.
 *
 * What it deliberately doesn't model:
 *   - Validation of content rules (e.g. `<table><row><cell>` ordering). The
 *     server side typically doesn't validate steps either — peers apply them
 *     via `receiveTransaction`, and the canonical schema is what gets
 *     enforced there. If our generated step JSON applies cleanly against
 *     the same `version` on a peer, we're good.
 */
import { type MarkSpec, type NodeSpec, Schema } from 'prosemirror-model'

export interface ProseMirrorNodeJSON {
    type: string
    content?: ProseMirrorNodeJSON[]
    text?: string
    attrs?: Record<string, unknown>
    marks?: Array<{ type: string; attrs?: Record<string, unknown> }>
}

interface DiscoveredTypes {
    nodes: Map<string, { hasContent: boolean; hasText: boolean }>
    marks: Set<string>
}

function discover(node: ProseMirrorNodeJSON, out: DiscoveredTypes): void {
    const name = typeof node.type === 'string' ? node.type : '_unknown'
    const existing = out.nodes.get(name) ?? { hasContent: false, hasText: false }
    if (Array.isArray(node.content) && node.content.length > 0) {
        existing.hasContent = true
    }
    if (typeof node.text === 'string') {
        existing.hasText = true
    }
    out.nodes.set(name, existing)
    for (const mark of node.marks ?? []) {
        if (mark && typeof mark.type === 'string') {
            out.marks.add(mark.type)
        }
    }
    for (const child of node.content ?? []) {
        discover(child, out)
    }
}

const TEXT_NODE = 'text'

/**
 * Build a ProseMirror Schema that accepts the given doc's full node/mark
 * vocabulary. Always includes `doc` and `text` even if the doc is empty.
 *
 * Group strategy:
 *   - Top-level children of `doc` go into `block`.
 *   - Anything that contains `text` becomes `content: 'inline*'` with group
 *     `block` (so it can sit inside `doc` and inside its own kind alike).
 *   - Pure containers (no text node but with children) get `content: 'block+'`
 *     and group `block`.
 *   - Leaves with no content become atomic block leaves — the safest default
 *     for unknown `ph-*` widgets so they round-trip without losing attrs.
 *   - `text` is always group `inline`.
 *
 * Attribute strategy:
 *   - Every non-text node accepts a single `attrs` object passthrough. We
 *     don't introspect attribute keys — the agent's input is rebuilt from the
 *     original JSON we just parsed, so attrs flow through unchanged.
 */
export function buildSchemaForDoc(doc: ProseMirrorNodeJSON | ProseMirrorNodeJSON[]): Schema {
    const discovered: DiscoveredTypes = { nodes: new Map(), marks: new Set() }
    const roots = Array.isArray(doc) ? doc : [doc]
    for (const root of roots) {
        discover(root, discovered)
    }

    // Always ensure foundational types exist even if the doc is degenerate.
    if (!discovered.nodes.has('doc')) {
        discovered.nodes.set('doc', { hasContent: true, hasText: false })
    }
    if (!discovered.nodes.has(TEXT_NODE)) {
        discovered.nodes.set(TEXT_NODE, { hasContent: false, hasText: true })
    }

    const nodes: Record<string, NodeSpec> = {}

    for (const [name, info] of discovered.nodes) {
        if (name === TEXT_NODE) {
            nodes[name] = { group: 'inline' }
            continue
        }

        if (name === 'doc') {
            // Doc is open-ended: any number of block children including zero,
            // which mirrors what happens when an agent deletes every block.
            nodes[name] = { content: 'block*' }
            continue
        }

        const passthroughAttrs: NodeSpec['attrs'] = { attrs: { default: null } }

        if (info.hasText) {
            // Inline-content block (paragraph, heading, code_block, ...).
            // Allow zero children so trailing-paragraph-like nodes parse.
            nodes[name] = {
                content: 'inline*',
                group: 'block',
                attrs: passthroughAttrs,
                marks: '_',
            }
            continue
        }

        if (info.hasContent) {
            // Container block (blockquote, bullet_list, list_item, table, ...).
            nodes[name] = {
                content: 'block*',
                group: 'block',
                attrs: passthroughAttrs,
                marks: '_',
            }
            continue
        }

        // Atomic leaf (ph-recording, image, horizontal_rule, ...).
        nodes[name] = {
            group: 'block',
            atom: true,
            attrs: passthroughAttrs,
        }
    }

    const marks: Record<string, MarkSpec> = {}
    for (const name of discovered.marks) {
        marks[name] = { attrs: { attrs: { default: null } } }
    }

    return new Schema({ nodes, marks })
}

/**
 * Pre-process a document JSON so it can be parsed by a schema that declares
 * a single `attrs` passthrough attribute. The wire format spreads node
 * attributes at the top level (`{ type: 'heading', attrs: { level: 1 } }`)
 * — our schema accepts an `attrs` attr of any shape, so we just leave the
 * original `attrs` object in place but pack it under our wrapper key. Marks
 * get the same treatment.
 */
export function packDocAttrs(json: ProseMirrorNodeJSON): ProseMirrorNodeJSON {
    const out: ProseMirrorNodeJSON = { type: json.type }
    if (json.type !== TEXT_NODE) {
        // Carry the original attrs object verbatim under our single passthrough key
        // so we never have to enumerate product-specific attribute names.
        if (json.attrs !== undefined) {
            out.attrs = { attrs: json.attrs as unknown as Record<string, unknown> }
        } else {
            out.attrs = { attrs: null as unknown as Record<string, unknown> }
        }
    }
    if (json.text !== undefined) {
        out.text = json.text
    }
    if (json.marks && json.marks.length > 0) {
        out.marks = json.marks.map((m) => ({
            type: m.type,
            attrs: m.attrs !== undefined ? { attrs: m.attrs } : { attrs: null as unknown as Record<string, unknown> },
        }))
    }
    if (json.content && json.content.length > 0) {
        out.content = json.content.map(packDocAttrs)
    }
    return out
}

/**
 * Inverse of `packDocAttrs` — recover the wire-format attribute shape so the
 * resulting `content` payload that we POST to `collab/save` matches what the
 * frontend would have produced.
 */
export function unpackDocAttrs(json: ProseMirrorNodeJSON): ProseMirrorNodeJSON {
    const out: ProseMirrorNodeJSON = { type: json.type }
    if (json.type !== TEXT_NODE) {
        const wrapped = json.attrs as { attrs?: unknown } | undefined
        const inner = wrapped && 'attrs' in wrapped ? wrapped.attrs : undefined
        if (inner !== undefined && inner !== null) {
            out.attrs = inner as Record<string, unknown>
        }
    }
    if (json.text !== undefined) {
        out.text = json.text
    }
    if (json.marks && json.marks.length > 0) {
        out.marks = json.marks.map((m) => {
            const wrappedMark = m.attrs as { attrs?: unknown } | undefined
            const innerMark = wrappedMark && 'attrs' in wrappedMark ? wrappedMark.attrs : undefined
            const result: { type: string; attrs?: Record<string, unknown> } = { type: m.type }
            if (innerMark !== undefined && innerMark !== null) {
                result.attrs = innerMark as Record<string, unknown>
            }
            return result
        })
    }
    if (json.content && json.content.length > 0) {
        out.content = json.content.map(unpackDocAttrs)
    }
    return out
}
