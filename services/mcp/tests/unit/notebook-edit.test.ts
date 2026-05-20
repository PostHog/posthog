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

interface MockRequestCall {
    method: string
    body?: any
}

interface MockState {
    notebookContent: typeof sampleDoc | Record<string, unknown> | null
    version: number
    requestCalls: MockRequestCall[]
    /** Programmable replies the mock POSTs through. `undefined` = treat as GET. */
    postResponses: Array<{ throwWith?: Error; resolveWith?: unknown }>
}

function createMockContext(state: MockState): Context {
    const requestMock = vi.fn(async (opts: { method: string; body?: any }) => {
        state.requestCalls.push({ method: opts.method, body: opts.body })
        if (opts.method === 'GET') {
            return {
                short_id: 'aBcD1234',
                content: state.notebookContent,
                version: state.version,
                title: 'Original',
            }
        }
        // POST
        const next = state.postResponses.shift()
        if (!next) {
            throw new Error('No queued POST response')
        }
        if (next.throwWith) {
            throw next.throwWith
        }
        return next.resolveWith
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
    it('happy path: returns the updated notebook from the server', async () => {
        const updatedNotebook = {
            short_id: 'aBcD1234',
            content: sampleDoc,
            version: 8,
            title: 'Original',
        }
        const state: MockState = {
            notebookContent: sampleDoc,
            version: 7,
            requestCalls: [],
            postResponses: [{ resolveWith: updatedNotebook }],
        }
        const context = createMockContext(state)

        const result = await editHandler(context, {
            short_id: 'aBcD1234',
            old_string: '"First paragraph."',
            new_string: '"First paragraph EDITED."',
        })

        expect(result).toEqual(updatedNotebook)
        // One GET + one POST.
        expect(state.requestCalls).toHaveLength(2)
        expect(state.requestCalls[0]!.method).toBe('GET')
        expect(state.requestCalls[1]!.method).toBe('POST')
        expect(state.requestCalls[1]!.body.version).toBe(7)
        expect(JSON.stringify(state.requestCalls[1]!.body.content)).toContain('First paragraph EDITED.')
    })

    it('throws when old_string does not appear', async () => {
        const state: MockState = {
            notebookContent: sampleDoc,
            version: 7,
            requestCalls: [],
            postResponses: [],
        }
        const context = createMockContext(state)
        await expect(
            editHandler(context, {
                short_id: 'aBcD1234',
                old_string: '"does not exist"',
                new_string: '"x"',
            })
        ).rejects.toThrow(/old_string was not found/)
        // Only the initial GET, no POST.
        expect(state.requestCalls.filter((c) => c.method === 'POST')).toHaveLength(0)
    })

    it('throws when old_string is ambiguous and replace_all is not set', async () => {
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
            requestCalls: [],
            postResponses: [],
        }
        const context = createMockContext(state)
        await expect(
            editHandler(context, {
                short_id: 'aBcD1234',
                old_string: '"duplicate"',
                new_string: '"unique"',
            })
        ).rejects.toThrow(/matches 2 places/)
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
            requestCalls: [],
            postResponses: [{ resolveWith: updated }],
        }
        const context = createMockContext(state)
        const result = await editHandler(context, {
            short_id: 'aBcD1234',
            old_string: '"duplicate"',
            new_string: '"unique"',
            replace_all: true,
        })
        expect(result).toEqual(updated)
        const postBody = state.requestCalls.find((c) => c.method === 'POST')!.body
        expect(JSON.stringify(postBody.content)).toContain('"text":"unique"')
        expect(JSON.stringify(postBody.content)).not.toContain('"text":"duplicate"')
    })

    it('throws when the replacement breaks JSON syntax', async () => {
        const state: MockState = {
            notebookContent: sampleDoc,
            version: 7,
            requestCalls: [],
            postResponses: [],
        }
        const context = createMockContext(state)
        await expect(
            editHandler(context, {
                short_id: 'aBcD1234',
                old_string: '"First paragraph."',
                new_string: '"First paragraph."}}}',
            })
        ).rejects.toThrow(/no longer valid JSON/)
    })

    it('propagates server errors verbatim (e.g. 409 from collab/save)', async () => {
        // The MCP `request()` helper turns any non-2xx into a thrown Error
        // whose message embeds the URL + status + raw response body. We rely
        // on that pass-through so the agent sees Django's actual response
        // (including `code: "conflict"` + `version` for 409, `detail` for
        // 410, etc.) rather than a wrapped/rewritten string.
        const djangoError = new Error(
            'Request failed:\nURL: POST /api/projects/42/notebooks/aBcD1234/collab/save/\n' +
                'Status Code: 409 (Conflict)\n' +
                'Error Message: {"code":"conflict","steps":[],"client_ids":[],"version":8}'
        )
        const state: MockState = {
            notebookContent: sampleDoc,
            version: 7,
            requestCalls: [],
            postResponses: [{ throwWith: djangoError }],
        }
        const context = createMockContext(state)
        await expect(
            editHandler(context, {
                short_id: 'aBcD1234',
                old_string: '"First paragraph."',
                new_string: '"updated"',
            })
        ).rejects.toThrow(djangoError)
    })

    it('throws when the notebook has no editable content', async () => {
        const state: MockState = {
            notebookContent: null,
            version: 7,
            requestCalls: [],
            postResponses: [],
        }
        const context = createMockContext(state)
        await expect(editHandler(context, { short_id: 'aBcD1234', old_string: 'a', new_string: 'b' })).rejects.toThrow(
            /no editable content/
        )
    })

    it('uses 2-space indent for the serialization the agent matches against', () => {
        expect(JSON_INDENT).toBe(2)
        const serialized = JSON.stringify(sampleDoc, null, JSON_INDENT)
        expect(serialized).toContain('  "type"')
        expect(serialized).toContain('      "type"')
    })
})
