// Side-effect: registers the surface's product data-tool renderers (incl. the notebook keys) into the
// shared registry. The bare registry no longer knows product keys, so the resolution assertions below need it.
import './registerDataToolRenderers'

import { lookupToolRenderer, toolRegistry } from 'products/posthog_ai/frontend/api/tools'
import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

import { extractNotebook } from './CreateNotebookWidget'

function toolMessage(rawOutput: unknown, innerInput?: Record<string, unknown>): ToolCallMessage {
    return {
        id: 'call-1',
        resolvedKey: 'notebooks-create',
        rawServerName: 'posthog',
        rawToolName: 'mcp__posthog__exec',
        rawInput: {},
        innerInput,
        rawOutput,
        content: [],
        status: 'completed',
    }
}

describe('CreateNotebookWidget', () => {
    it.each([
        'notebooks-create',
        'notebooks-partial-update',
        'notebooks-retrieve',
        'notebook-edit',
        'notebooks-create-markdown',
        'notebooks-get',
    ])('resolves %s to the notebook widget', (key) => {
        expect(toolRegistry.lookup(key)?.displayName).toBe('Notebook')
        // The notebook widget is gated on a trusted PostHog-exec origin, so pass `fromPostHogExec`.
        expect(lookupToolRenderer(key, true).displayName).toBe('Notebook')
    })

    it('falls back to the generic renderer for an unknown inner tool key', () => {
        expect(lookupToolRenderer('some-unwired-tool', true).displayName).not.toBe('Notebook')
    })

    describe('extractNotebook', () => {
        // The rich-text tools spell the short id `short_id` and surround it with the rest of the REST
        // record; the markdown tools spell it `notebook_id`. Both reduce to the same extraction.
        it.each([
            [
                'short_id',
                {
                    id: 'b3d0f2aa-1111-2222-3333-444455556666',
                    short_id: 'aBcDe123',
                    content: { type: 'doc', content: [] },
                    version: 1,
                },
            ],
            ['notebook_id', { notebook_id: 'aBcDe123' }],
        ])('reads the short id from %s, with the title and the _posthogUrl enrichment', (_field, payload) => {
            const notebook = extractNotebook(
                toolMessage({
                    ...payload,
                    title: 'Churn deep dive',
                    _posthogUrl: 'https://us.posthog.com/project/1/notebooks/aBcDe123',
                })
            )
            expect(notebook).toEqual({
                shortId: 'aBcDe123',
                title: 'Churn deep dive',
                url: 'https://us.posthog.com/project/1/notebooks/aBcDe123',
            })
        })

        it('falls back to the input title when the payload title is missing', () => {
            const notebook = extractNotebook(toolMessage({ short_id: 'aBcDe123' }, { title: 'From input' }))
            expect(notebook).toEqual({ shortId: 'aBcDe123', title: 'From input', url: undefined })
        })

        it('returns null for outputs carrying neither id or that are not objects', () => {
            expect(extractNotebook(toolMessage({ blocks: [], title: 'Legacy artifact shape' }))).toBeNull()
            expect(extractNotebook(toolMessage('created notebook aBcDe123'))).toBeNull()
            expect(extractNotebook(toolMessage(undefined))).toBeNull()
        })
    })
})
