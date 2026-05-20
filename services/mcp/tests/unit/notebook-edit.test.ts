import { describe, expect, it, vi } from 'vitest'

import { editHandler, JSON_INDENT, NotebookEditSchema } from '@/tools/notebooks/edit'
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
    /**
     * Current "server view" of the notebook. Every GET returns the latest
     * values. Tests can mutate these between operations to simulate a
     * concurrent edit landing on the server.
     */
    notebookContent: typeof sampleDoc | Record<string, unknown>
    version: number
    saveCalls: Array<{ body: any }>
    /** GET call counter — useful for tests that want to verify refetch happened. */
    getCalls: number
    /**
     * Optional callback fired AFTER each POST resolves, before the next GET.
     * Use this to mutate `notebookContent` + `version` to simulate a
     * concurrent edit having landed in between.
     */
    onPost?: (postIndex: number) => void
    saveResponses: Array<{ status: number; body: unknown }>
}

function createMockContext(state: MockState): Context {
    const requestMock = vi.fn(async () => {
        state.getCalls++
        return {
            short_id: 'aBcD1234',
            content: state.notebookContent,
            version: state.version,
            title: 'Original',
        }
    })
    const requestRawMock = vi.fn(async (opts: { body: any }) => {
        const idx = state.saveCalls.length
        state.saveCalls.push({ body: opts.body })
        const response = state.saveResponses.shift()
        if (!response) {
            throw new Error('No queued response for requestRaw call')
        }
        state.onPost?.(idx)
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
            getCalls: 0,
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
        expect(result.conflicts).toBe(0)
        expect(state.saveCalls).toHaveLength(1)
        // The text we sent up should reflect the change.
        expect(JSON.stringify(state.saveCalls[0]!.body.content)).toContain('First paragraph EDITED.')
    })

    it('returns not_found when old_string does not appear', async () => {
        const state: MockState = {
            notebookContent: sampleDoc,
            version: 7,
            saveCalls: [],
            getCalls: 0,
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
            getCalls: 0,
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
        expect((result.error as unknown as { match_count: number }).match_count).toBe(2)
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
            getCalls: 0,
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
            getCalls: 0,
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

    it('handles 409 by refetching and re-running str_replace', async () => {
        // Simulate: agent reads notebook at version 7, computes edit, POSTs.
        // Server has moved on to version 8 due to a concurrent edit that
        // renamed the heading but didn't touch the paragraph we're editing.
        // Server returns 409. We refetch (now seeing version 8 + the
        // concurrent rename), re-run str_replace against the new content
        // (which still contains "First paragraph." — the concurrent edit
        // didn't touch it), and POST again with version 8.
        const concurrentEditedDoc = {
            ...sampleDoc,
            content: [
                { type: 'heading', attrs: { level: 1 }, content: [{ type: 'text', text: 'Renamed' }] },
                sampleDoc.content[1],
                sampleDoc.content[2],
                sampleDoc.content[3],
            ],
        }
        const state: MockState = {
            notebookContent: sampleDoc,
            version: 7,
            saveCalls: [],
            getCalls: 0,
            // Simulate the server-side state moving forward to version 8
            // between our 1st POST (which 409s) and our refetch.
            onPost: (idx) => {
                if (idx === 0) {
                    state.notebookContent = concurrentEditedDoc as unknown as typeof sampleDoc
                    state.version = 8
                }
            },
            saveResponses: [
                { status: 409, body: { code: 'conflict' } },
                {
                    status: 200,
                    body: {
                        short_id: 'aBcD1234',
                        content: concurrentEditedDoc,
                        version: 9,
                        title: 'Original',
                    },
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
        expect(result.conflicts).toBe(1)
        // 2 GETs (initial + refetch) and 2 POSTs (initial 409 + retry 200).
        expect(state.getCalls).toBe(2)
        expect(state.saveCalls).toHaveLength(2)
        // Second POST targets version 8 — the version we refetched.
        expect(state.saveCalls[1]!.body.version).toBe(8)
        // And carries the renamed heading from the concurrent edit, proving
        // we computed against the refetched state rather than rebasing locally.
        expect(JSON.stringify(state.saveCalls[1]!.body.content)).toContain('Renamed')
    })

    it('on 409, surfaces a clean not_found if the concurrent edit removed the target', async () => {
        // Simulate: someone else deleted "First paragraph." between our
        // initial GET and our POST. After 409, refetch sees no match and we
        // return the agent a structured `not_found` instead of silently
        // doing nothing or merging anyway.
        const deletedDoc = {
            ...sampleDoc,
            content: [sampleDoc.content[0], sampleDoc.content[2], sampleDoc.content[3]],
        }
        const state: MockState = {
            notebookContent: sampleDoc,
            version: 7,
            saveCalls: [],
            getCalls: 0,
            onPost: (idx) => {
                if (idx === 0) {
                    state.notebookContent = deletedDoc as unknown as typeof sampleDoc
                    state.version = 8
                }
            },
            saveResponses: [{ status: 409, body: { code: 'conflict' } }],
        }
        const context = createMockContext(state)
        const result = await editHandler(context, {
            short_id: 'aBcD1234',
            old_string: '"First paragraph."',
            new_string: '"First paragraph EDITED."',
        })
        expect(result.isError).toBe(true)
        if (!result.isError) {
            return
        }
        expect((result.error as { code: string }).code).toBe('not_found')
        // Only the initial POST happened; after 409, refetch reveals not_found
        // before we attempt a second POST.
        expect(state.saveCalls).toHaveLength(1)
    })

    it('returns stale_buffer on 410', async () => {
        const state: MockState = {
            notebookContent: sampleDoc,
            version: 7,
            saveCalls: [],
            getCalls: 0,
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
            getCalls: 0,
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
