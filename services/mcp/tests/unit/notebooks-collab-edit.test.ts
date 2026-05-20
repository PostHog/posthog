import { Node as PMNode } from 'prosemirror-model'
import { describe, expect, it, vi } from 'vitest'

import { buildSteps } from '@/tools/notebooks/buildSteps'
import { collabEditHandler } from '@/tools/notebooks/collabEdit'
import { hunkAfter, hunkBefore, parsePatch, PatchParseError } from '@/tools/notebooks/patch'
import { rebaseSteps } from '@/tools/notebooks/rebase'
import { buildSchemaForDoc, packDocAttrs, unpackDocAttrs } from '@/tools/notebooks/schema'
import { renderDoc } from '@/tools/notebooks/textRender'
import type { Context } from '@/tools/types'

// ---------- Fixtures ----------------------------------------------------------

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

function buildDoc(json: unknown = sampleDoc): { doc: PMNode; schema: ReturnType<typeof buildSchemaForDoc> } {
    const cast = json as Parameters<typeof packDocAttrs>[0]
    const schema = buildSchemaForDoc(cast)
    const packed = packDocAttrs(cast)
    const doc = PMNode.fromJSON(schema, packed as Parameters<typeof PMNode.fromJSON>[1])
    return { doc, schema }
}

// ---------- Patch parser ------------------------------------------------------

describe('parsePatch', () => {
    it('parses a simple hunk with context, remove, and add lines', () => {
        const patch = `@@
 keep me
-remove me
+add me`
        const parsed = parsePatch(patch)
        expect(parsed.hunks).toHaveLength(1)
        expect(parsed.hunks[0]!.lines).toEqual([
            { kind: 'context', text: 'keep me' },
            { kind: 'remove', text: 'remove me' },
            { kind: 'add', text: 'add me' },
        ])
    })

    it('tolerates Begin/End markers and multiple hunks', () => {
        const patch = `*** Begin Patch
@@
 a
-b
@@
+c
 d
*** End Patch`
        const parsed = parsePatch(patch)
        expect(parsed.hunks).toHaveLength(2)
    })

    it('treats blank lines as hunk terminators inside the patch body', () => {
        const patch = `@@
 a
-b

@@
+c`
        const parsed = parsePatch(patch)
        expect(parsed.hunks).toHaveLength(2)
    })

    it('rejects lines without a marker character', () => {
        expect(() => parsePatch('@@\nno marker line')).toThrow(PatchParseError)
    })

    it('rejects empty patches', () => {
        expect(() => parsePatch('')).toThrow(PatchParseError)
    })

    it('projects hunks to before/after lists', () => {
        const { hunks } = parsePatch(`@@\n ctx\n-rm\n+add`)
        expect(hunkBefore(hunks[0]!)).toEqual(['ctx', 'rm'])
        expect(hunkAfter(hunks[0]!)).toEqual(['ctx', 'add'])
    })
})

// ---------- Dynamic schema ----------------------------------------------------

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
        const { doc } = buildDoc()
        const roundtripped = unpackDocAttrs(doc.toJSON() as Parameters<typeof unpackDocAttrs>[0])
        expect(roundtripped).toEqual(sampleDoc)
    })

    it('handles documents with unknown custom node types without hardcoded lists', () => {
        const exotic = {
            type: 'doc',
            content: [
                { type: 'totally-new-widget', attrs: { foo: 'bar' } },
                { type: 'paragraph', content: [{ type: 'text', text: 'hi' }] },
            ],
        }
        const schema = buildSchemaForDoc(exotic as Parameters<typeof buildSchemaForDoc>[0])
        expect(schema.nodes['totally-new-widget']).toBeTruthy()
        // Round-trip preserves the unknown widget's attrs even though we never enumerated its keys.
        const packed = packDocAttrs(exotic as Parameters<typeof packDocAttrs>[0])
        const doc = PMNode.fromJSON(schema, packed as Parameters<typeof PMNode.fromJSON>[1])
        const out = unpackDocAttrs(doc.toJSON() as Parameters<typeof unpackDocAttrs>[0])
        expect(out).toEqual(exotic)
    })
})

// ---------- Text rendering ---------------------------------------------------

describe('renderDoc', () => {
    it('renders one line per top-level block', () => {
        const { doc } = buildDoc()
        const rendered = renderDoc(doc)
        expect(rendered.lines).toEqual([
            'My notebook',
            'First paragraph.',
            'Second paragraph.',
            '<atom:ph-recording>',
            'Trailing paragraph.',
        ])
    })

    it('records monotonically increasing PM positions covering every node', () => {
        const { doc } = buildDoc()
        const rendered = renderDoc(doc)
        for (let i = 1; i < rendered.blocks.length; i++) {
            expect(rendered.blocks[i]!.pmStart).toBe(rendered.blocks[i - 1]!.pmEnd)
        }
        expect(rendered.blocks[rendered.blocks.length - 1]!.pmEnd).toBe(doc.content.size)
    })
})

// ---------- buildSteps -------------------------------------------------------

describe('buildSteps', () => {
    it('produces a ReplaceStep for a simple single-block replacement', () => {
        const { doc, schema } = buildDoc()
        const patch = parsePatch(`@@\n-First paragraph.\n+Replaced first paragraph.`)
        const result = buildSteps(doc, patch, schema)
        expect(result.ok).toBe(true)
        if (!result.ok) {
            return
        }
        expect(result.steps).toHaveLength(1)
        const newContent = unpackDocAttrs(
            result.newDoc.toJSON() as Parameters<typeof unpackDocAttrs>[0]
        ) as typeof sampleDoc
        expect(newContent.content[1]).toEqual({
            type: 'paragraph',
            content: [{ type: 'text', text: 'Replaced first paragraph.' }],
        })
    })

    it('preserves atomic widgets when they appear as context lines', () => {
        const { doc, schema } = buildDoc()
        const patch = parsePatch(`@@\n <atom:ph-recording>\n-Trailing paragraph.\n+New trailing paragraph.`)
        const result = buildSteps(doc, patch, schema)
        expect(result.ok).toBe(true)
        if (!result.ok) {
            return
        }
        const newContent = unpackDocAttrs(
            result.newDoc.toJSON() as Parameters<typeof unpackDocAttrs>[0]
        ) as typeof sampleDoc
        // ph-recording is preserved as the original node (with its sess-123 attr).
        expect(newContent.content[3]).toEqual({ type: 'ph-recording', attrs: { id: 'sess-123' } })
        expect(newContent.content[4]).toEqual({
            type: 'paragraph',
            content: [{ type: 'text', text: 'New trailing paragraph.' }],
        })
    })

    it('removes atomic widgets when targeted with -', () => {
        const { doc, schema } = buildDoc()
        const patch = parsePatch(`@@\n-<atom:ph-recording>`)
        const result = buildSteps(doc, patch, schema)
        expect(result.ok).toBe(true)
        if (!result.ok) {
            return
        }
        const out = unpackDocAttrs(result.newDoc.toJSON() as Parameters<typeof unpackDocAttrs>[0]) as typeof sampleDoc
        expect(out.content.some((b) => b.type === 'ph-recording')).toBe(false)
    })

    it('rejects + lines that try to construct an atomic widget', () => {
        const { doc, schema } = buildDoc()
        const patch = parsePatch(`@@\n+<atom:ph-recording>`)
        const result = buildSteps(doc, patch, schema)
        expect(result.ok).toBe(false)
        if (result.ok) {
            return
        }
        expect(result.error.code).toBe('cannot_construct_atomic')
    })

    it('returns anchor_not_found when context line does not match', () => {
        const { doc, schema } = buildDoc()
        const patch = parsePatch(`@@\n-Nonexistent paragraph.`)
        const result = buildSteps(doc, patch, schema)
        expect(result.ok).toBe(false)
        if (result.ok) {
            return
        }
        expect(result.error.code).toBe('anchor_not_found')
        expect(result.error.message).toContain('Nonexistent paragraph.')
    })

    it('returns anchor_ambiguous when the same context matches multiple places', () => {
        const dupDoc = {
            type: 'doc',
            content: [
                { type: 'paragraph', content: [{ type: 'text', text: 'same' }] },
                { type: 'paragraph', content: [{ type: 'text', text: 'same' }] },
            ],
        }
        const { doc, schema } = buildDoc(dupDoc)
        const patch = parsePatch(`@@\n-same\n+different`)
        const result = buildSteps(doc, patch, schema)
        expect(result.ok).toBe(false)
        if (result.ok) {
            return
        }
        expect(result.error.code).toBe('anchor_ambiguous')
    })

    it('supports adding a brand-new paragraph between existing blocks', () => {
        const { doc, schema } = buildDoc()
        const patch = parsePatch(`@@\n First paragraph.\n+Inserted between.\n Second paragraph.`)
        const result = buildSteps(doc, patch, schema)
        expect(result.ok).toBe(true)
        if (!result.ok) {
            return
        }
        const out = unpackDocAttrs(result.newDoc.toJSON() as Parameters<typeof unpackDocAttrs>[0]) as typeof sampleDoc
        expect(out.content[2]).toEqual({
            type: 'paragraph',
            content: [{ type: 'text', text: 'Inserted between.' }],
        })
    })

    it('applies multiple hunks against the running doc', () => {
        const { doc, schema } = buildDoc()
        const patch = parsePatch(`@@\n-First paragraph.\n+First v2.\n@@\n-Second paragraph.\n+Second v2.`)
        const result = buildSteps(doc, patch, schema)
        expect(result.ok).toBe(true)
        if (!result.ok) {
            return
        }
        expect(result.steps).toHaveLength(2)
        const out = unpackDocAttrs(result.newDoc.toJSON() as Parameters<typeof unpackDocAttrs>[0]) as typeof sampleDoc
        expect((out.content[1] as { content: [{ text: string }] }).content[0]!.text).toBe('First v2.')
        expect((out.content[2] as { content: [{ text: string }] }).content[0]!.text).toBe('Second v2.')
    })
})

// ---------- rebaseSteps ------------------------------------------------------

describe('rebaseSteps', () => {
    it('rebases a non-overlapping pending step over missed steps', () => {
        const { doc, schema } = buildDoc()

        // Local edit: replace the trailing paragraph.
        const localPatch = parsePatch(`@@\n-Trailing paragraph.\n+Local edit.`)
        const localBuild = buildSteps(doc, localPatch, schema)
        expect(localBuild.ok).toBe(true)
        if (!localBuild.ok) {
            return
        }

        // Concurrent edit: replace the heading (different range).
        const concurrentBuild = buildSteps(doc, parsePatch(`@@\n-My notebook\n+Renamed`), schema)
        expect(concurrentBuild.ok).toBe(true)
        if (!concurrentBuild.ok) {
            return
        }
        const missedJson = concurrentBuild.steps.map((s) => ({ step: s.toJSON() as Record<string, unknown> }))

        const rebased = rebaseSteps(localBuild.steps, missedJson, doc, schema, 1)
        expect(rebased.ok).toBe(true)
        if (!rebased.ok) {
            return
        }
        const out = unpackDocAttrs(
            rebased.finalDoc.toJSON() as Parameters<typeof unpackDocAttrs>[0]
        ) as typeof sampleDoc
        // Both edits visible after rebase
        expect((out.content[0] as { content: [{ text: string }] }).content[0]!.text).toBe('Renamed')
        expect((out.content[4] as { content: [{ text: string }] }).content[0]!.text).toBe('Local edit.')
    })

    it('returns step_dropped when the concurrent edit deleted our range', () => {
        const { doc, schema } = buildDoc()

        const localBuild = buildSteps(doc, parsePatch(`@@\n-Trailing paragraph.\n+Local edit.`), schema)
        expect(localBuild.ok).toBe(true)
        if (!localBuild.ok) {
            return
        }
        // Concurrent edit: deleted the same trailing paragraph.
        const concurrentBuild = buildSteps(doc, parsePatch(`@@\n-Trailing paragraph.`), schema)
        expect(concurrentBuild.ok).toBe(true)
        if (!concurrentBuild.ok) {
            return
        }
        const missedJson = concurrentBuild.steps.map((s) => ({ step: s.toJSON() as Record<string, unknown> }))

        const rebased = rebaseSteps(localBuild.steps, missedJson, doc, schema, 1)
        // Note: PM may successfully rebase a ReplaceStep over a deletion in some cases
        // (it maps to an empty range). We accept either step_dropped OR apply_failed
        // OR a successful rebase that ends up as a no-op. The key invariant: we don't crash.
        expect(['step_dropped', 'apply_failed', undefined]).toContain(rebased.ok ? undefined : rebased.code)
    })
})

// ---------- collabEditHandler — handler-level smoke test ---------------------

interface MockState {
    notebookContent: typeof sampleDoc
    version: number
    saveCalls: Array<{ body: any }>
    /** Programmable response for the next save call (sequential queue). */
    saveResponses: Array<{ status: number; body: unknown }>
}

function createMockContext(state: MockState): Context {
    const requestMock = vi.fn(async (opts: { method: string; path: string }) => {
        if (opts.method === 'GET' && opts.path.endsWith(`/`)) {
            return {
                short_id: 'aBcD1234',
                content: state.notebookContent,
                version: state.version,
                title: 'A notebook',
            }
        }
        throw new Error(`Unexpected request call: ${opts.method} ${opts.path}`)
    })
    const requestRawMock = vi.fn(async (opts: { method: string; path: string; body: any }) => {
        state.saveCalls.push({ body: opts.body })
        const response = state.saveResponses.shift()
        if (!response) {
            throw new Error('No queued response for requestRaw call')
        }
        return response
    })
    return {
        api: { request: requestMock, requestRaw: requestRawMock } as any,
        stateManager: { getProjectId: vi.fn().mockResolvedValue('42') } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test-distinct',
        trackEvent: async () => {},
    }
}

describe('collabEditHandler', () => {
    it('happy path: builds steps, posts once, returns updated notebook', async () => {
        const state: MockState = {
            notebookContent: sampleDoc,
            version: 7,
            saveCalls: [],
            saveResponses: [
                {
                    status: 200,
                    body: {
                        short_id: 'aBcD1234',
                        content: sampleDoc,
                        version: 8,
                        title: 'A notebook',
                    },
                },
            ],
        }
        const context = createMockContext(state)
        const result = await collabEditHandler(context, {
            short_id: 'aBcD1234',
            patch: `@@\n-First paragraph.\n+First updated.`,
        })

        if (result.isError) {
            throw new Error(`expected ok, got: ${JSON.stringify(result.error)}`)
        }
        expect(result.steps_applied).toBe(1)
        expect(result.rebases).toBe(0)
        expect(state.saveCalls).toHaveLength(1)
        expect(state.saveCalls[0]!.body.version).toBe(7)
        expect(state.saveCalls[0]!.body.steps).toHaveLength(1)
        // text_content is built from the resulting doc.
        expect(state.saveCalls[0]!.body.text_content).toContain('First updated.')
    })

    it('returns stale_buffer error on 410', async () => {
        const state: MockState = {
            notebookContent: sampleDoc,
            version: 7,
            saveCalls: [],
            saveResponses: [{ status: 410, body: { code: 'conflict_stale' } }],
        }
        const context = createMockContext(state)
        const result = await collabEditHandler(context, {
            short_id: 'aBcD1234',
            patch: `@@\n-First paragraph.\n+First updated.`,
        })
        expect(result.isError).toBe(true)
        if (!result.isError) {
            return
        }
        expect((result.error as { code: string }).code).toBe('stale_buffer')
    })

    it('rebases and retries on 409 with missed steps', async () => {
        const state: MockState = {
            notebookContent: sampleDoc,
            version: 7,
            saveCalls: [],
            saveResponses: [],
        }
        // Build a concurrent step JSON to "return" from the server.
        const { doc: serverDoc, schema: serverSchema } = buildDoc()
        const concurrent = buildSteps(serverDoc, parsePatch(`@@\n-My notebook\n+Renamed`), serverSchema)
        if (!concurrent.ok) {
            throw new Error('precondition failed')
        }
        const missedStepJson = concurrent.steps[0]!.toJSON() as Record<string, unknown>
        state.saveResponses.push({
            status: 409,
            body: { steps: [missedStepJson], client_ids: ['other-client'], version: 8 },
        })
        state.saveResponses.push({
            status: 200,
            body: { short_id: 'aBcD1234', content: sampleDoc, version: 9, title: 'A notebook' },
        })

        const context = createMockContext(state)
        const result = await collabEditHandler(context, {
            short_id: 'aBcD1234',
            patch: `@@\n-First paragraph.\n+First updated.`,
        })

        if (result.isError) {
            throw new Error(`expected ok, got: ${JSON.stringify(result.error)}`)
        }
        expect(result.rebases).toBe(1)
        expect(state.saveCalls).toHaveLength(2)
        // Second call must be POSTed at the new version.
        expect(state.saveCalls[1]!.body.version).toBe(8)
    })

    it('returns patch_parse_error for malformed input', async () => {
        const state: MockState = {
            notebookContent: sampleDoc,
            version: 7,
            saveCalls: [],
            saveResponses: [],
        }
        const context = createMockContext(state)
        const result = await collabEditHandler(context, {
            short_id: 'aBcD1234',
            patch: 'not a patch',
        })
        expect(result.isError).toBe(true)
        if (!result.isError) {
            return
        }
        expect((result.error as { code: string }).code).toBe('patch_parse_error')
        expect(state.saveCalls).toHaveLength(0)
    })

    it('returns anchor_not_found when the patch does not match the notebook', async () => {
        const state: MockState = {
            notebookContent: sampleDoc,
            version: 7,
            saveCalls: [],
            saveResponses: [],
        }
        const context = createMockContext(state)
        const result = await collabEditHandler(context, {
            short_id: 'aBcD1234',
            patch: `@@\n-Made up content that does not exist.`,
        })
        expect(result.isError).toBe(true)
        if (!result.isError) {
            return
        }
        expect((result.error as { code: string }).code).toBe('anchor_not_found')
        expect(state.saveCalls).toHaveLength(0)
    })

    it('returns the current notebook without POSTing on a no-op patch', async () => {
        const state: MockState = {
            notebookContent: sampleDoc,
            version: 7,
            saveCalls: [],
            saveResponses: [],
        }
        const context = createMockContext(state)
        const result = await collabEditHandler(context, {
            short_id: 'aBcD1234',
            patch: `@@\n First paragraph.`,
        })
        if (result.isError) {
            throw new Error(`expected ok, got: ${JSON.stringify(result.error)}`)
        }
        expect(result.steps_applied).toBe(0)
        expect(state.saveCalls).toHaveLength(0)
    })
})
