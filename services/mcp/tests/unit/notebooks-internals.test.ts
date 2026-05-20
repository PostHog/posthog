/**
 * Direct tests for the shared notebooks editing primitives — the dynamic
 * ProseMirror schema and the Mapping-based step rebaser. These two modules
 * are used by `notebook-edit` (and would be used by any future tool that
 * routes through `collab/save`), so it's worth pinning their behaviour
 * independently of the tool's end-to-end flow.
 */
import { Node as PMNode } from 'prosemirror-model'
import { describe, expect, it } from 'vitest'

import { diffDocsToSteps } from '@/tools/notebooks/diffSteps'
import { rebaseSteps } from '@/tools/notebooks/rebase'
import { buildSchemaForDoc, packDocAttrs, unpackDocAttrs } from '@/tools/notebooks/schema'

const sampleDoc = {
    type: 'doc',
    content: [
        { type: 'heading', attrs: { level: 1 }, content: [{ type: 'text', text: 'My notebook' }] },
        { type: 'paragraph', content: [{ type: 'text', text: 'First paragraph.' }] },
        { type: 'paragraph', content: [{ type: 'text', text: 'Second paragraph.' }] },
        { type: 'ph-recording', attrs: { id: 'sess-123' } },
        { type: 'paragraph', content: [{ type: 'text', text: 'Trailing paragraph.' }] },
    ],
}

type DocJson = Parameters<typeof packDocAttrs>[0]
type DocSchema = ReturnType<typeof buildSchemaForDoc>

function buildOn(schema: DocSchema, json: unknown): PMNode {
    return PMNode.fromJSON(schema, packDocAttrs(json as DocJson) as Parameters<typeof PMNode.fromJSON>[1])
}

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
        expect(schema.nodes['ph-recording']).toBeTruthy()
    })

    it('round-trips a notebook doc through pack → fromJSON → toJSON → unpack', () => {
        const { doc } = buildDoc(sampleDoc)
        const roundtripped = unpackDocAttrs(doc.toJSON() as Parameters<typeof unpackDocAttrs>[0])
        expect(roundtripped).toEqual(sampleDoc)
    })

    it('handles documents with unknown custom node types without hardcoded lists', () => {
        // The whole point of the dynamic schema: new ph-* widgets added in
        // the frontend don't require any MCP change. We round-trip an
        // invented widget here to prove the schema discovers it.
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
        // The str-replace tool may produce a `newDoc` that introduces a node
        // type not present in the original. Passing both roots ensures the
        // resulting schema can parse either.
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

describe('rebaseSteps', () => {
    it('rebases a non-overlapping pending step over missed steps', () => {
        // All three docs share one schema: any step built against any of them
        // must be applicable against any of the others. This mirrors what the
        // real handler does (one schema for the whole tool invocation).
        const pendingNew = {
            ...sampleDoc,
            content: [
                sampleDoc.content[0],
                sampleDoc.content[1],
                sampleDoc.content[2],
                sampleDoc.content[3],
                { type: 'paragraph', content: [{ type: 'text', text: 'Local edit.' }] },
            ],
        }
        const concurrentNew = {
            ...sampleDoc,
            content: [
                { type: 'heading', attrs: { level: 1 }, content: [{ type: 'text', text: 'Renamed' }] },
                sampleDoc.content[1],
                sampleDoc.content[2],
                sampleDoc.content[3],
                sampleDoc.content[4],
            ],
        }
        const schema = buildSchemaForDoc([sampleDoc as DocJson, pendingNew as DocJson, concurrentNew as DocJson])
        const baseDoc = buildOn(schema, sampleDoc)

        const pendingDiff = diffDocsToSteps(baseDoc, buildOn(schema, pendingNew))
        const concurrentDiff = diffDocsToSteps(baseDoc, buildOn(schema, concurrentNew))
        if (!pendingDiff.ok || !concurrentDiff.ok) {
            throw new Error('precondition: both diffs should succeed')
        }
        const missedJson = concurrentDiff.steps.map((s) => ({ step: s.toJSON() as Record<string, unknown> }))

        const rebased = rebaseSteps(pendingDiff.steps, missedJson, baseDoc, schema, 1)
        expect(rebased.ok).toBe(true)
        if (!rebased.ok) {
            return
        }
        const out = unpackDocAttrs(
            rebased.finalDoc.toJSON() as Parameters<typeof unpackDocAttrs>[0]
        ) as typeof sampleDoc
        // Both edits visible after rebase.
        expect((out.content[0] as { content: [{ text: string }] }).content[0]!.text).toBe('Renamed')
        expect((out.content[4] as { content: [{ text: string }] }).content[0]!.text).toBe('Local edit.')
    })

    it('does not crash on a concurrent edit that deleted our target range', () => {
        const pendingNew = {
            ...sampleDoc,
            content: [
                sampleDoc.content[0],
                sampleDoc.content[1],
                sampleDoc.content[2],
                sampleDoc.content[3],
                { type: 'paragraph', content: [{ type: 'text', text: 'Local edit.' }] },
            ],
        }
        // Concurrent edit deletes the same trailing paragraph we're trying to replace.
        const concurrentNew = {
            ...sampleDoc,
            content: [sampleDoc.content[0], sampleDoc.content[1], sampleDoc.content[2], sampleDoc.content[3]],
        }
        const schema = buildSchemaForDoc([sampleDoc as DocJson, pendingNew as DocJson, concurrentNew as DocJson])
        const baseDoc = buildOn(schema, sampleDoc)

        const pendingDiff = diffDocsToSteps(baseDoc, buildOn(schema, pendingNew))
        const concurrentDiff = diffDocsToSteps(baseDoc, buildOn(schema, concurrentNew))
        if (!pendingDiff.ok || !concurrentDiff.ok) {
            throw new Error('precondition: both diffs should succeed')
        }
        const missedJson = concurrentDiff.steps.map((s) => ({ step: s.toJSON() as Record<string, unknown> }))

        const rebased = rebaseSteps(pendingDiff.steps, missedJson, baseDoc, schema, 1)
        // PM may successfully rebase a ReplaceStep over a deletion in some
        // cases (mapping to an empty range) — we accept either step_dropped,
        // apply_failed, or a successful rebase that ends up as a no-op. The
        // contract under test is: we do not crash.
        expect(['step_dropped', 'apply_failed', undefined]).toContain(rebased.ok ? undefined : rebased.code)
    })
})
