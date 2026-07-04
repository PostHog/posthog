import { describe, expect, it, vi } from 'vitest'

import { PostHogApiError } from '@/lib/errors'
import { editHandler, NotebookEditSchema } from '@/tools/notebooks/edit'
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
    it('rejects identical old_value and new_value (deep-equal)', () => {
        const result = NotebookEditSchema.safeParse({
            short_id: 'abc',
            old_value: { type: 'text', text: 'same' },
            // Different key order, same value — must still be rejected as deep-equal.
            new_value: { text: 'same', type: 'text' },
        })
        expect(result.success).toBe(false)
    })

    it('accepts a minimal valid payload', () => {
        const result = NotebookEditSchema.safeParse({
            short_id: 'abc',
            old_value: { type: 'text', text: 'a' },
            new_value: { type: 'text', text: 'b' },
        })
        expect(result.success).toBe(true)
    })

    it('accepts replace_all', () => {
        const result = NotebookEditSchema.safeParse({
            short_id: 'abc',
            old_value: { type: 'text', text: 'a' },
            new_value: { type: 'text', text: 'b' },
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
    it('happy path: replaces a text node by value and returns the updated notebook', async () => {
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
            old_value: { type: 'text', text: 'First paragraph.' },
            new_value: { type: 'text', text: 'First paragraph EDITED.' },
        })

        // Returns the full notebook from the server (already includes new content + bumped version).
        expect(result).toEqual(updatedNotebook)
        expect(state.saveCalls).toHaveLength(1)
        expect(state.saveCalls[0]!.body.version).toBe(7)
        expect(JSON.stringify(state.saveCalls[0]!.body.content)).toContain('First paragraph EDITED.')
    })

    it('emits a step trimmed to the changed block, not a full-doc replace', async () => {
        // Position math for `sampleDoc` (each open/close token is one position):
        //   heading "Sample Notebook"        (15 text chars + 2 wrap)  → 17 positions  [0, 17)
        //   paragraph "First paragraph."     (16 text chars + 2 wrap)  → 18 positions  [17, 35)
        //   paragraph "Second paragraph."    (17 text chars + 2 wrap)  → 19 positions  [35, 54)
        //   ph-recording atom                                          → 1 position    [54, 55)
        // ⇒ doc.content.size = 55
        //
        // Editing "First paragraph." → "First paragraph EDITED." only changes
        // the second top-level block. The trimmed step replaces just that block's
        // range [17, 35] with one new paragraph, instead of overwriting [0, 55]
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

        await editHandler(context, {
            short_id: 'aBcD1234',
            old_value: { type: 'text', text: 'First paragraph.' },
            new_value: { type: 'text', text: 'First paragraph EDITED.' },
        })

        const steps = state.saveCalls[0]!.body.steps as Array<{
            stepType: string
            from: number
            to: number
            slice?: { content: Array<{ type: string; content?: Array<{ type: string; text?: string }> }> }
        }>
        expect(steps).toHaveLength(1)
        expect(steps[0]!.stepType).toBe('replace')
        expect(steps[0]!.from).toBe(17)
        expect(steps[0]!.to).toBe(35)
        // Slice contains exactly one paragraph block with the edited text.
        const sliceBlocks = steps[0]!.slice?.content ?? []
        expect(sliceBlocks).toHaveLength(1)
        expect(sliceBlocks[0]!.type).toBe('paragraph')
        expect(sliceBlocks[0]!.content?.[0]).toMatchObject({ type: 'text', text: 'First paragraph EDITED.' })
    })

    it('matches by deep equality regardless of key order in the agent input', async () => {
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
            // Reverse key order from how the doc stores it (`type` then `text`):
            old_value: { text: 'First paragraph.', type: 'text' },
            new_value: { type: 'text', text: 'First paragraph EDITED.' },
        })

        expect(result).toEqual(updatedNotebook)
        expect(JSON.stringify(state.saveCalls[0]!.body.content)).toContain('First paragraph EDITED.')
    })

    it('throws not-found error when old_value matches no subtree', async () => {
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
                old_value: { type: 'text', text: 'This text does not exist anywhere' },
                new_value: { type: 'text', text: 'replacement' },
            })
        ).rejects.toThrow(/old_value was not found/)
        expect(state.saveCalls).toHaveLength(0)
    })

    it('throws ambiguous error when old_value matches more than one subtree without replace_all', async () => {
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
                old_value: { type: 'text', text: 'duplicate' },
                new_value: { type: 'text', text: 'unique' },
            })
        ).rejects.toThrow(/matches 2 places/)
        expect(state.saveCalls).toHaveLength(0)
    })

    it('replaces every matching subtree when replace_all is true', async () => {
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
            old_value: { type: 'text', text: 'duplicate' },
            new_value: { type: 'text', text: 'unique' },
            replace_all: true,
        })
        expect(result).toEqual(updated)
        expect(JSON.stringify(state.saveCalls[0]!.body.content)).toContain('"text":"unique"')
        expect(JSON.stringify(state.saveCalls[0]!.body.content)).not.toContain('"text":"duplicate"')
    })

    it('appends sibling blocks when new_value is an array (splice, not nest)', async () => {
        // Regression: replacing a single content-array node with an array `new_value`
        // used to nest the array inside the content array, so `Node.fromJSON` saw a
        // child with `.type === undefined` and threw "Unknown node type: undefined".
        // The array must be spliced in, producing flat sibling blocks — this is the
        // documented append path.
        const updated = { short_id: 'aBcD1234', content: sampleDoc, version: 8, title: 'Original' }
        const state: MockState = {
            notebookContent: sampleDoc,
            version: 7,
            saveCalls: [],
            getCalls: 0,
            saveResponses: [{ ok: true, body: updated }],
        }
        const context = createMockContext(state)

        await editHandler(context, {
            short_id: 'aBcD1234',
            old_value: { type: 'paragraph', content: [{ type: 'text', text: 'Second paragraph.' }] },
            new_value: [
                { type: 'paragraph', content: [{ type: 'text', text: 'Second paragraph.' }] },
                { type: 'paragraph', content: [{ type: 'text', text: 'Appended paragraph.' }] },
            ],
        })

        // Save succeeded (no parse error) and both the original and the new sibling survive.
        expect(state.saveCalls).toHaveLength(1)
        const savedContent = state.saveCalls[0]!.body.content as { content: Array<{ type: string }> }
        expect(savedContent.content).toHaveLength(sampleDoc.content.length + 1)
        const serialized = JSON.stringify(savedContent)
        expect(serialized).toContain('Second paragraph.')
        expect(serialized).toContain('Appended paragraph.')
        // No nested array leaked into the content list.
        expect(savedContent.content.every((node) => !Array.isArray(node))).toBe(true)
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
                old_value: { type: 'text', text: 'First paragraph.' },
                new_value: { type: 'text', text: 'First paragraph EDITED.' },
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
        await expect(
            editHandler(context, {
                short_id: 'aBcD1234',
                old_value: { type: 'text', text: 'a' },
                new_value: { type: 'text', text: 'b' },
            })
        ).rejects.toThrow(/no editable content/)
    })
})
