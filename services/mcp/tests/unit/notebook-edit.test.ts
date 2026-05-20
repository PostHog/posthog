import { describe, expect, it, vi } from 'vitest'

import { PostHogApiError } from '@/lib/errors'
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
        const result = NotebookEditSchema.safeParse({ short_id: 'abc', old_string: 'a', new_string: 'b' })
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
    notebookContent: typeof sampleDoc | Record<string, unknown> | null
    version: number
    saveCalls: Array<{ body: any }>
    getCalls: number
    /**
     * Queued POST responses. Each entry is either a successful body (returned
     * as-is) or an error to throw (e.g. PostHogApiError for 409/410).
     */
    saveResponses: Array<{ ok: true; body: unknown } | { ok: false; error: Error }>
}

function createMockContext(state: MockState): Context {
    const requestMock = vi.fn(async (opts: { method: string; body?: any }) => {
        if (opts.method === 'GET') {
            state.getCalls++
            return {
                short_id: 'aBcD1234',
                content: state.notebookContent,
                version: state.version,
                title: 'Original',
            }
        }
        // POST → collab/save
        state.saveCalls.push({ body: opts.body })
        const response = state.saveResponses.shift()
        if (!response) {
            throw new Error('No queued response for save call')
        }
        if (!response.ok) {
            throw response.error
        }
        return response.body
    })
    return {
        api: { request: requestMock } as any,
        stateManager: { getProjectId: vi.fn().mockResolvedValue('42') } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test',
        trackEvent: async () => {},
    }
}

describe('editHandler', () => {
    it('happy path: returns the updated notebook with new content', async () => {
        const updatedNotebook = {
            short_id: 'aBcD1234',
            content: sampleDoc,
            version: 8,
            title: 'Original',
        }
        const state: MockState = {
            notebookContent: sampleDoc,
            version: 7,
            saveCalls: [],
            getCalls: 0,
            saveResponses: [{ ok: true, body: updatedNotebook }],
        }
        const context = createMockContext(state)

        const result = await editHandler(context, {
            short_id: 'aBcD1234',
            old_string: '"First paragraph."',
            new_string: '"First paragraph EDITED."',
        })

        // Returns the full notebook from the server (already includes new content + bumped version).
        expect(result).toEqual(updatedNotebook)
        expect(state.saveCalls).toHaveLength(1)
        expect(state.saveCalls[0]!.body.version).toBe(7)
        expect(JSON.stringify(state.saveCalls[0]!.body.content)).toContain('First paragraph EDITED.')
    })

    it('throws not-found error when old_string does not appear', async () => {
        const state: MockState = {
            notebookContent: sampleDoc,
            version: 7,
            saveCalls: [],
            getCalls: 0,
            saveResponses: [],
        }
        const context = createMockContext(state)
        await expect(
            editHandler(context, {
                short_id: 'aBcD1234',
                old_string: '"This text does not exist anywhere"',
                new_string: '"replacement"',
            })
        ).rejects.toThrow(/old_string was not found/)
        expect(state.saveCalls).toHaveLength(0)
    })

    it('throws ambiguous error when old_string matches more than once without replace_all', async () => {
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
        await expect(
            editHandler(context, {
                short_id: 'aBcD1234',
                old_string: '"duplicate"',
                new_string: '"unique"',
            })
        ).rejects.toThrow(/matches 2 places/)
        expect(state.saveCalls).toHaveLength(0)
    })

    it('replaces every occurrence when replace_all is true', async () => {
        const dupDoc = {
            type: 'doc',
            content: [
                { type: 'paragraph', content: [{ type: 'text', text: 'duplicate' }] },
                { type: 'paragraph', content: [{ type: 'text', text: 'duplicate' }] },
            ],
        }
        const updated = { short_id: 'aBcD1234', content: dupDoc, version: 8, title: 'x' }
        const state: MockState = {
            notebookContent: dupDoc as unknown as typeof sampleDoc,
            version: 7,
            saveCalls: [],
            getCalls: 0,
            saveResponses: [{ ok: true, body: updated }],
        }
        const context = createMockContext(state)
        const result = await editHandler(context, {
            short_id: 'aBcD1234',
            old_string: '"duplicate"',
            new_string: '"unique"',
            replace_all: true,
        })
        expect(result).toEqual(updated)
        expect(JSON.stringify(state.saveCalls[0]!.body.content)).toContain('"text":"unique"')
        expect(JSON.stringify(state.saveCalls[0]!.body.content)).not.toContain('"text":"duplicate"')
    })

    it('throws when the replacement breaks JSON syntax', async () => {
        const state: MockState = {
            notebookContent: sampleDoc,
            version: 7,
            saveCalls: [],
            getCalls: 0,
            saveResponses: [],
        }
        const context = createMockContext(state)
        await expect(
            editHandler(context, {
                short_id: 'aBcD1234',
                old_string: '"First paragraph."',
                new_string: '"First paragraph."}}}',
            })
        ).rejects.toThrow(/no longer valid JSON/)
        expect(state.saveCalls).toHaveLength(0)
    })

    it('lets server errors (e.g. 409 conflict) propagate verbatim for handleToolError to format', async () => {
        // The Django collab/save handler returns a 409 body that already
        // contains the latest version + the rebased steps the agent needs to
        // retry. We rely on PostHogApiError carrying status + body through to
        // handleToolError, which surfaces them to the agent — no bespoke
        // refetch / re-render in the tool itself.
        const conflictBody = JSON.stringify({
            code: 'conflict',
            version: 8,
            steps: [{ stepType: 'replace', from: 0, to: 5 }],
            client_ids: ['someone-else'],
        })
        const state: MockState = {
            notebookContent: sampleDoc,
            version: 7,
            saveCalls: [],
            getCalls: 0,
            saveResponses: [
                {
                    ok: false,
                    error: new PostHogApiError({
                        status: 409,
                        statusText: 'Conflict',
                        body: conflictBody,
                        url: 'http://test/api/projects/42/notebooks/aBcD1234/collab/save/',
                        method: 'POST',
                    }),
                },
            ],
        }
        const context = createMockContext(state)

        await expect(
            editHandler(context, {
                short_id: 'aBcD1234',
                old_string: '"First paragraph."',
                new_string: '"First paragraph EDITED."',
            })
        ).rejects.toMatchObject({
            name: 'PostHogApiError',
            status: 409,
            body: conflictBody,
        })
        // POST attempted exactly once — no client-side retry, no extra GET.
        expect(state.saveCalls).toHaveLength(1)
        expect(state.getCalls).toBe(1)
    })

    it('throws when the notebook has no editable content', async () => {
        const state: MockState = {
            notebookContent: null,
            version: 7,
            saveCalls: [],
            getCalls: 0,
            saveResponses: [],
        }
        const context = createMockContext(state)
        await expect(editHandler(context, { short_id: 'aBcD1234', old_string: 'a', new_string: 'b' })).rejects.toThrow(
            /no editable content/
        )
    })

    it('uses 2-space indent for the serialization the agent matches against', () => {
        // Sanity check that JSON_INDENT is exposed and the tool description
        // accurately reflects what the agent will see.
        expect(JSON_INDENT).toBe(2)
        const serialized = JSON.stringify(sampleDoc, null, JSON_INDENT)
        expect(serialized).toContain('  "type"')
        expect(serialized).toContain('      "type"')
    })
})
