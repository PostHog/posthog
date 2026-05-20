/**
 * Direct tests for the generic ProseMirror primitives in `lib/prosemirror/`.
 * These modules know nothing about MCP, notebooks, or any specific product —
 * they're pure functions over ProseMirror documents. Worth pinning their
 * behaviour independently of any caller.
 */
import { Node as PMNode } from 'prosemirror-model'
import { describe, expect, it } from 'vitest'

import { diffDocsToSteps } from '@/lib/prosemirror/diff'
import { buildSchemaForDoc, packDocAttrs, unpackDocAttrs } from '@/lib/prosemirror/schema'

const sampleDoc = {
    type: 'doc',
    content: [
        { type: 'heading', attrs: { level: 1 }, content: [{ type: 'text', text: 'My doc' }] },
        { type: 'paragraph', content: [{ type: 'text', text: 'First paragraph.' }] },
        { type: 'paragraph', content: [{ type: 'text', text: 'Second paragraph.' }] },
        { type: 'custom-widget', attrs: { id: 'sess-123' } },
        { type: 'paragraph', content: [{ type: 'text', text: 'Trailing paragraph.' }] },
    ],
}

type DocJson = Parameters<typeof packDocAttrs>[0]

function buildDoc(json: unknown): {
    doc: PMNode
    schema: ReturnType<typeof buildSchemaForDoc>
} {
    const cast = json as DocJson
    const schema = buildSchemaForDoc(cast)
    const doc = PMNode.fromJSON(schema, packDocAttrs(cast) as Parameters<typeof PMNode.fromJSON>[1])
    return { doc, schema }
}

describe('buildSchemaForDoc', () => {
    it('discovers every node type used in the doc', () => {
        const schema = buildSchemaForDoc(sampleDoc as Parameters<typeof buildSchemaForDoc>[0])
        expect(schema.nodes.doc).toBeTruthy()
        expect(schema.nodes.paragraph).toBeTruthy()
        expect(schema.nodes.heading).toBeTruthy()
        expect(schema.nodes.text).toBeTruthy()
        expect(schema.nodes['custom-widget']).toBeTruthy()
    })

    it('round-trips a doc through pack → fromJSON → toJSON → unpack', () => {
        const { doc } = buildDoc(sampleDoc)
        const roundtripped = unpackDocAttrs(doc.toJSON() as Parameters<typeof unpackDocAttrs>[0])
        expect(roundtripped).toEqual(sampleDoc)
    })

    it('handles documents with unknown custom node types without hardcoded lists', () => {
        // The whole point of the dynamic schema: a new widget type added in the
        // frontend (or anywhere else) doesn't require any change here. We
        // round-trip an invented widget to prove the schema discovers it.
        const exotic = {
            type: 'doc',
            content: [
                { type: 'totally-new-widget', attrs: { foo: 'bar' } },
                { type: 'paragraph', content: [{ type: 'text', text: 'hi' }] },
            ],
        }
        const schema = buildSchemaForDoc(exotic as Parameters<typeof buildSchemaForDoc>[0])
        expect(schema.nodes['totally-new-widget']).toBeTruthy()
        const packed = packDocAttrs(exotic as Parameters<typeof packDocAttrs>[0])
        const doc = PMNode.fromJSON(schema, packed as Parameters<typeof PMNode.fromJSON>[1])
        const out = unpackDocAttrs(doc.toJSON() as Parameters<typeof unpackDocAttrs>[0])
        expect(out).toEqual(exotic)
    })

    it('builds a single schema covering the union of multiple root docs', () => {
        // Callers that need to parse two related docs (e.g. an "old" and a
        // "new" version for diffing) can pass both — the resulting schema
        // covers every node type appearing in either.
        const oldDoc = {
            type: 'doc',
            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'a' }] }],
        }
        const newDoc = {
            type: 'doc',
            content: [
                { type: 'paragraph', content: [{ type: 'text', text: 'a' }] },
                { type: 'brand-new-type', attrs: { x: 1 } },
            ],
        }
        const schema = buildSchemaForDoc([oldDoc as DocJson, newDoc as DocJson])
        expect(schema.nodes['brand-new-type']).toBeTruthy()
    })
})

describe('diffDocsToSteps', () => {
    function buildPair(oldJson: unknown, newJson: unknown): { oldDoc: PMNode; newDoc: PMNode } {
        // Both docs share one schema so steps built against newDoc apply to oldDoc.
        const a = oldJson as DocJson
        const b = newJson as DocJson
        const schema = buildSchemaForDoc([a, b])
        return {
            oldDoc: PMNode.fromJSON(schema, packDocAttrs(a) as Parameters<typeof PMNode.fromJSON>[1]),
            newDoc: PMNode.fromJSON(schema, packDocAttrs(b) as Parameters<typeof PMNode.fromJSON>[1]),
        }
    }

    it('produces zero steps for identical docs', () => {
        const { oldDoc, newDoc } = buildPair(sampleDoc, sampleDoc)
        const result = diffDocsToSteps(oldDoc, newDoc)
        expect(result.ok).toBe(true)
        if (result.ok) {
            expect(result.steps).toHaveLength(0)
        }
    })

    it('produces a single ReplaceStep covering one changed block', () => {
        const newJson = {
            ...sampleDoc,
            content: [
                sampleDoc.content[0],
                { type: 'paragraph', content: [{ type: 'text', text: 'First paragraph CHANGED.' }] },
                sampleDoc.content[2],
                sampleDoc.content[3],
                sampleDoc.content[4],
            ],
        }
        const { oldDoc, newDoc } = buildPair(sampleDoc, newJson)
        const result = diffDocsToSteps(oldDoc, newDoc)
        expect(result.ok).toBe(true)
        if (!result.ok) {
            return
        }
        expect(result.steps).toHaveLength(1)
        // The step's range should cover only the second block.
        const headingSize = oldDoc.maybeChild(0)!.nodeSize
        const paragraph1Size = oldDoc.maybeChild(1)!.nodeSize
        const stepJson = result.steps[0]!.toJSON() as { from: number; to: number }
        expect(stepJson.from).toBe(headingSize)
        expect(stepJson.to).toBe(headingSize + paragraph1Size)
    })

    it('handles pure insertion (new block between existing ones)', () => {
        const newJson = {
            ...sampleDoc,
            content: [
                sampleDoc.content[0],
                sampleDoc.content[1],
                { type: 'paragraph', content: [{ type: 'text', text: 'Inserted.' }] },
                sampleDoc.content[2],
                sampleDoc.content[3],
                sampleDoc.content[4],
            ],
        }
        const { oldDoc, newDoc } = buildPair(sampleDoc, newJson)
        const result = diffDocsToSteps(oldDoc, newDoc)
        expect(result.ok).toBe(true)
        if (!result.ok) {
            return
        }
        expect(result.steps).toHaveLength(1)
    })

    it('handles pure deletion (removing a block)', () => {
        const newJson = {
            ...sampleDoc,
            content: [sampleDoc.content[0], sampleDoc.content[2], sampleDoc.content[3], sampleDoc.content[4]],
        }
        const { oldDoc, newDoc } = buildPair(sampleDoc, newJson)
        const result = diffDocsToSteps(oldDoc, newDoc)
        expect(result.ok).toBe(true)
        if (!result.ok) {
            return
        }
        expect(result.steps).toHaveLength(1)
    })
})
