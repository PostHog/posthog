import { Node as PMNode } from 'prosemirror-model'
import { describe, expect, it, vi } from 'vitest'

import { diffDocsToSteps } from '@/tools/notebooks/diffSteps'
import { editHandler, JSON_INDENT, NotebookEditSchema } from '@/tools/notebooks/edit'
import { buildSchemaForDoc, packDocAttrs } from '@/tools/notebooks/schema'
import type { Context } from '@/tools/types'

const sampleDoc = {
    type: 'doc',
    content: [
        { type: 'heading', attrs: { level: 1 }, content: [{ type: 'text', text: 'Sample Notebook' }] },
        { type: 'paragraph', content: [{ type: 'text', text: 'First paragraph.' }] },
        { type: 'paragraph', content: [{ type: 'text', text: 'Second paragraph.' }] },
        { type: 'ph-recording', attrs: { id: 'sess-123' } },
    ],
}

// ---------- diffDocsToSteps --------------------------------------------------

describe('diffDocsToSteps', () => {
    function buildPair(oldJson: unknown, newJson: unknown): { oldDoc: PMNode; newDoc: PMNode } {
        // Both docs MUST share the same schema instance, otherwise the steps
        // built against newDoc's node types won't apply to oldDoc.
        const a = oldJson as Parameters<typeof packDocAttrs>[0]
        const b = newJson as Parameters<typeof packDocAttrs>[0]
        const schema = buildSchemaForDoc([a, b])
        return {
            oldDoc: PMNode.fromJSON(schema, packDocAttrs(a) as Parameters<typeof PMNode.fromJSON>[1]),
            newDoc: PMNode.fromJSON(schema, packDocAttrs(b) as Parameters<typeof PMNode.fromJSON>[1]),
        }
    }
    function build(json: unknown): PMNode {
        return buildPair(json, json).oldDoc
    }

    it('produces zero steps for identical docs', () => {
        const a = build(sampleDoc)
        const b = build(sampleDoc)
        const result = diffDocsToSteps(a, b)
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
            ],
        }
        const { oldDoc, newDoc } = buildPair(sampleDoc, newJson)
        const result = diffDocsToSteps(oldDoc, newDoc)
        expect(result.ok).toBe(true)
        if (!result.ok) {
            return
        }
        expect(result.steps).toHaveLength(1)
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
            content: [sampleDoc.content[0], sampleDoc.content[2], sampleDoc.content[3]],
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

// ---------- Input schema -----------------------------------------------------

describe('NotebookEditSchema', () => {
    it('rejects identical old_string and new_string', () => {
        const result = NotebookEditSchema.safeParse({
            short_id: 'abc',
            old_string: 'same',
            new_string: 'same',
        })
        expect(result.success).toBe(false)
    })

    it('accepts a minimal valid payload', () => {
        const result = NotebookEditSchema.safeParse({
            short_id: 'abc',
            old_string: 'a',
            new_string: 'b',
        })
        expect(result.success).toBe(true)
    })

    it('accepts replace_all', () => {
        const result = NotebookEditSchema.safeParse({
            short_id: 'abc',
            old_string: 'a',
            new_string: 'b',
            replace_all: true,
        })
        expect(result.success).toBe(true)
    })
})

// ---------- editHandler — handler-level smoke test --------------------------

interface MockState {
    notebookContent: typeof sampleDoc
    version: number
    saveCalls: Array<{ body: any }>
    saveResponses: Array<{ status: number; body: unknown }>
}

function createMockContext(state: MockState): Context {
    const requestMock = vi.fn(async () => ({
        short_id: 'aBcD1234',
        content: state.notebookContent,
        version: state.version,
        title: 'Original',
    }))
    const requestRawMock = vi.fn(async (opts: { body: any }) => {
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
        getDistinctId: async () => 'test',
        trackEvent: async () => {},
    }
}

describe('editHandler', () => {
    it('happy path: matches old_string against serialized content, posts steps', async () => {
        const state: MockState = {
            notebookContent: sampleDoc,
            version: 7,
            saveCalls: [],
            saveResponses: [
                {
                    status: 200,
                    body: { short_id: 'aBcD1234', content: sampleDoc, version: 8, title: 'Original' },
                },
            ],
        }
        const context = createMockContext(state)

        // old_string is a literal substring of JSON.stringify(content, null, 2).
        // Pull it from the actual serialization to avoid hand-counting indents.
        const serialized = JSON.stringify(sampleDoc, null, JSON_INDENT)
        const targetIdx = serialized.indexOf('"First paragraph."')
        expect(targetIdx).toBeGreaterThan(0)
        const oldString = '"First paragraph."'
        const newString = '"First paragraph EDITED."'

        const result = await editHandler(context, {
            short_id: 'aBcD1234',
            old_string: oldString,
            new_string: newString,
        })

        if (result.isError) {
            throw new Error(`expected ok, got: ${JSON.stringify(result.error)}`)
        }
        expect(result.replacements).toBe(1)
        expect(result.steps_applied).toBe(1)
        expect(result.rebases).toBe(0)
        expect(state.saveCalls).toHaveLength(1)
        // The text we sent up should reflect the change.
        expect(JSON.stringify(state.saveCalls[0]!.body.content)).toContain('First paragraph EDITED.')
    })

    it('returns not_found when old_string does not appear', async () => {
        const state: MockState = {
            notebookContent: sampleDoc,
            version: 7,
            saveCalls: [],
            saveResponses: [],
        }
        const context = createMockContext(state)
        const result = await editHandler(context, {
            short_id: 'aBcD1234',
            old_string: '"This text does not exist anywhere"',
            new_string: '"replacement"',
        })
        expect(result.isError).toBe(true)
        if (!result.isError) {
            return
        }
        expect((result.error as { code: string }).code).toBe('not_found')
        expect(state.saveCalls).toHaveLength(0)
    })

    it('returns ambiguous when old_string matches more than once without replace_all', async () => {
        const dupDoc = {
            type: 'doc',
            content: [
                { type: 'paragraph', content: [{ type: 'text', text: 'duplicate' }] },
                { type: 'paragraph', content: [{ type: 'text', text: 'duplicate' }] },
            ],
        }
        const state: MockState = {
            notebookContent: dupDoc as unknown as typeof sampleDoc,
            version: 7,
            saveCalls: [],
            saveResponses: [],
        }
        const context = createMockContext(state)
        const result = await editHandler(context, {
            short_id: 'aBcD1234',
            old_string: '"duplicate"',
            new_string: '"unique"',
        })
        expect(result.isError).toBe(true)
        if (!result.isError) {
            return
        }
        expect((result.error as { code: string }).code).toBe('ambiguous')
        expect((result.error as { match_count: number }).match_count).toBe(2)
    })

    it('replaces every occurrence when replace_all is true', async () => {
        const dupDoc = {
            type: 'doc',
            content: [
                { type: 'paragraph', content: [{ type: 'text', text: 'duplicate' }] },
                { type: 'paragraph', content: [{ type: 'text', text: 'duplicate' }] },
            ],
        }
        const state: MockState = {
            notebookContent: dupDoc as unknown as typeof sampleDoc,
            version: 7,
            saveCalls: [],
            saveResponses: [
                {
                    status: 200,
                    body: { short_id: 'aBcD1234', content: dupDoc, version: 8, title: 'x' },
                },
            ],
        }
        const context = createMockContext(state)
        const result = await editHandler(context, {
            short_id: 'aBcD1234',
            old_string: '"duplicate"',
            new_string: '"unique"',
            replace_all: true,
        })

        if (result.isError) {
            throw new Error(`expected ok, got: ${JSON.stringify(result.error)}`)
        }
        expect(result.replacements).toBe(2)
        expect(JSON.stringify(state.saveCalls[0]!.body.content)).toContain('"text":"unique"')
        expect(JSON.stringify(state.saveCalls[0]!.body.content)).not.toContain('"text":"duplicate"')
    })

    it('returns invalid_resulting_json when the replacement breaks JSON syntax', async () => {
        const state: MockState = {
            notebookContent: sampleDoc,
            version: 7,
            saveCalls: [],
            saveResponses: [],
        }
        const context = createMockContext(state)
        // Replace one of the closing braces with garbage so the result no longer parses.
        const result = await editHandler(context, {
            short_id: 'aBcD1234',
            old_string: '"First paragraph."',
            new_string: '"First paragraph."}}}',
        })
        expect(result.isError).toBe(true)
        if (!result.isError) {
            return
        }
        expect((result.error as { code: string }).code).toBe('invalid_resulting_json')
        expect(state.saveCalls).toHaveLength(0)
    })

    it('handles 409 by rebasing and retrying', async () => {
        // Construct a concurrent step JSON that touches a DIFFERENT block from
        // our edit so the rebase can succeed.
        const concurrentNewDoc = {
            ...sampleDoc,
            content: [
                { type: 'heading', attrs: { level: 1 }, content: [{ type: 'text', text: 'Renamed' }] },
                sampleDoc.content[1],
                sampleDoc.content[2],
                sampleDoc.content[3],
            ],
        }
        const oldPmDoc = (() => {
            const cast = sampleDoc as unknown as Parameters<typeof packDocAttrs>[0]
            const schema = buildSchemaForDoc(cast)
            return {
                doc: PMNode.fromJSON(schema, packDocAttrs(cast) as Parameters<typeof PMNode.fromJSON>[1]),
                schema,
            }
        })()
        const concurrentPmDoc = PMNode.fromJSON(
            oldPmDoc.schema,
            packDocAttrs(concurrentNewDoc as unknown as Parameters<typeof packDocAttrs>[0]) as Parameters<
                typeof PMNode.fromJSON
            >[1]
        )
        const concurrentDiff = diffDocsToSteps(oldPmDoc.doc, concurrentPmDoc)
        if (!concurrentDiff.ok || concurrentDiff.steps.length === 0) {
            throw new Error('precondition failed: concurrent edit should produce one step')
        }
        const missedStepJson = concurrentDiff.steps[0]!.toJSON() as Record<string, unknown>

        const state: MockState = {
            notebookContent: sampleDoc,
            version: 7,
            saveCalls: [],
            saveResponses: [
                {
                    status: 409,
                    body: { steps: [missedStepJson], client_ids: ['other-client'], version: 8 },
                },
                {
                    status: 200,
                    body: { short_id: 'aBcD1234', content: sampleDoc, version: 9, title: 'x' },
                },
            ],
        }
        const context = createMockContext(state)
        const result = await editHandler(context, {
            short_id: 'aBcD1234',
            old_string: '"First paragraph."',
            new_string: '"First paragraph EDITED."',
        })

        if (result.isError) {
            throw new Error(`expected ok, got: ${JSON.stringify(result.error)}`)
        }
        expect(result.rebases).toBe(1)
        expect(state.saveCalls).toHaveLength(2)
        expect(state.saveCalls[1]!.body.version).toBe(8)
    })

    it('returns stale_buffer on 410', async () => {
        const state: MockState = {
            notebookContent: sampleDoc,
            version: 7,
            saveCalls: [],
            saveResponses: [{ status: 410, body: { code: 'conflict_stale' } }],
        }
        const context = createMockContext(state)
        const result = await editHandler(context, {
            short_id: 'aBcD1234',
            old_string: '"First paragraph."',
            new_string: '"updated"',
        })
        expect(result.isError).toBe(true)
        if (!result.isError) {
            return
        }
        expect((result.error as { code: string }).code).toBe('stale_buffer')
    })

    it('returns no_content when the notebook has no editable content', async () => {
        const state: MockState = {
            notebookContent: null as unknown as typeof sampleDoc,
            version: 7,
            saveCalls: [],
            saveResponses: [],
        }
        const context = createMockContext(state)
        const result = await editHandler(context, {
            short_id: 'aBcD1234',
            old_string: 'a',
            new_string: 'b',
        })
        expect(result.isError).toBe(true)
        if (!result.isError) {
            return
        }
        expect((result.error as { code: string }).code).toBe('no_content')
    })

    it('uses 2-space indent for the serialization the agent matches against', () => {
        // Sanity check that JSON_INDENT is exposed and the tool description
        // accurately reflects what the agent will see. Nested levels accumulate
        // (level 2 = 4 spaces, level 3 = 6 spaces, etc.) which is expected and
        // what makes deeply-anchored old_strings recognizable for the agent.
        expect(JSON_INDENT).toBe(2)
        const serialized = JSON.stringify(sampleDoc, null, JSON_INDENT)
        expect(serialized).toContain('  "type"') // level-1 indent
        expect(serialized).toContain('      "type"') // level-3 indent (inside content array)
    })
})
