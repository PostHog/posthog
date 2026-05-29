import { describe, expect, it, vi } from 'vitest'

import { editHandler, NotebookEditSchema } from '@/tools/notebooks/editByReplacement'
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

describe('NotebookEditSchema', () => {
    it('rejects identical old_value and new_value (deep-equal)', () => {
        const result = NotebookEditSchema.safeParse({
            short_id: 'abc',
            old_value: { type: 'text', text: 'same' },
            new_value: { text: 'same', type: 'text' },
        })
        expect(result.success).toBe(false)
    })

    it('accepts subtree replacement input', () => {
        const result = NotebookEditSchema.safeParse({
            short_id: 'abc',
            old_value: { type: 'text', text: 'a' },
            new_value: { type: 'text', text: 'b' },
        })
        expect(result.success).toBe(true)
    })

    it('accepts anchored edits input', () => {
        const result = NotebookEditSchema.safeParse({
            short_id: 'abc',
            edits: [{ type: 'replace_text', find: 'a', replace: 'b', all_occurrences: false, occurrence: 1 }],
        })
        expect(result.success).toBe(true)
    })
})

interface MockState {
    notebookContent: typeof sampleDoc | Record<string, unknown> | null
    version: number
    saveCalls: Array<{ body: any }>
    getCalls: number
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
        api: {
            request: requestMock,
            getProjectBaseUrl: (projectId: string) => `https://app.posthog.com/project/${projectId}`,
        } as any,
        stateManager: {
            getProjectId: vi.fn().mockResolvedValue('42'),
            getAnalyticsContext: vi.fn().mockResolvedValue({ organizationId: 'org1', projectUuid: 'proj1' }),
        } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test',
        trackEvent: async () => {},
    }
}

describe('editHandler subtree replacement compatibility', () => {
    it('maps text-node old_value/new_value to replace_text', async () => {
        const updatedNotebook = { short_id: 'aBcD1234', content: sampleDoc, version: 8, title: 'Original' }
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

        expect(result).toEqual(updatedNotebook)
        expect(state.saveCalls).toHaveLength(1)
        expect(state.saveCalls[0]!.body.version).toBe(7)
        expect(JSON.stringify(state.saveCalls[0]!.body.content)).toContain('First paragraph EDITED.')
    })

    it('maps top-level old_value/new_value blocks to replace_subtree', async () => {
        const updatedNotebook = { short_id: 'aBcD1234', content: sampleDoc, version: 8, title: 'Original' }
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
            old_value: { type: 'paragraph', content: [{ type: 'text', text: 'Second paragraph.' }] },
            new_value: { type: 'paragraph', content: [{ type: 'text', text: 'Second paragraph EDITED.' }] },
        })

        const steps = state.saveCalls[0]!.body.steps as Array<{ from: number; to: number; stepType: string }>
        expect(steps).toEqual([{ stepType: 'replace', from: 35, to: 54, slice: expect.any(Object) }])
        expect(JSON.stringify(state.saveCalls[0]!.body.content)).toContain('Second paragraph EDITED.')
    })

    it('throws when old_value matches no content', async () => {
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
        ).rejects.toThrow(/Could not find text|old_node was not found/)
        expect(state.saveCalls).toHaveLength(0)
    })

    it('throws when the notebook has no editable content', async () => {
        const state: MockState = { notebookContent: null, version: 7, saveCalls: [], getCalls: 0, saveResponses: [] }
        const context = createMockContext(state)

        await expect(
            editHandler(context, {
                short_id: 'aBcD1234',
                old_value: { type: 'paragraph', content: [{ type: 'text', text: 'a' }] },
                new_value: { type: 'paragraph', content: [{ type: 'text', text: 'b' }] },
            })
        ).rejects.toThrow(/old_node was not found|no editable content/)
    })
})
