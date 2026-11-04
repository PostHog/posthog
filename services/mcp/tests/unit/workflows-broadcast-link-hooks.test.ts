import { describe, expect, it } from 'vitest'

import type { Context } from '@/tools/types'
import hooks from '@/tools/workflows/broadcastLinkHooks'

const context = {
    stateManager: { getProjectId: async () => '7' },
    api: { getProjectBaseUrl: (projectId: string) => `https://app.example.com/project/${projectId}` },
} as unknown as Context

const WORKFLOW_URL = 'https://app.example.com/project/7/workflows/abc/workflow'
const BROADCAST_URL = 'https://app.example.com/project/7/broadcasts/abc'
const oneEmailBatch = {
    id: 'abc',
    status: 'draft',
    origin_product: null,
    exit_condition: 'exit_only_at_end',
    draft: null,
    actions: [
        { id: 't', type: 'trigger', config: { type: 'batch', filters: {} } },
        { id: 'e', type: 'function_email', config: {} },
        { id: 'x', type: 'exit', config: {} },
    ],
    edges: [
        { from: 't', to: 'e' },
        { from: 'e', to: 'x' },
    ],
}

describe('broadcastLinkHooks', () => {
    it.each([
        {
            name: 'a broadcast links to the broadcast scene',
            flow: { origin_product: 'broadcasts' },
            url: BROADCAST_URL,
        },
        {
            name: 'an archived broadcast still links to the broadcast scene',
            flow: { origin_product: 'broadcasts', status: 'archived' },
            url: BROADCAST_URL,
        },
        { name: 'a one-email batch workflow suggests a broadcast', flow: {}, note: 'workflows-convert-to-broadcast' },
        {
            name: 'the default exit condition asks for exit_only_at_end first',
            flow: { exit_condition: 'exit_on_conversion' },
            note: 'exit_only_at_end',
        },
        {
            name: 'a workflow with more steps is left alone',
            flow: { actions: [...oneEmailBatch.actions, { id: 'd', type: 'delay', config: {} }] },
        },
        {
            name: 'an event trigger is left alone',
            flow: {
                actions: [{ id: 't', type: 'trigger', config: { type: 'event' } }, ...oneEmailBatch.actions.slice(1)],
            },
        },
        { name: 'an email that skips to the exit is left alone', flow: { edges: [{ from: 't', to: 'x' }] } },
        { name: 'a staged draft is left alone', flow: { draft: { actions: [] } } },
        { name: 'an archived workflow is left alone', flow: { status: 'archived' } },
        { name: 'a workflow another product owns is left alone', flow: { origin_product: 'surveys' } },
    ])('$name', async ({ flow, url, note }) => {
        const result = (await hooks.afterResponse(context, {}, { ...oneEmailBatch, ...flow })) as {
            _posthogUrl: string
            _agentNote?: string
        }

        expect(result._posthogUrl).toBe(url ?? WORKFLOW_URL)
        if (note) {
            expect(result._agentNote).toContain(note)
        } else {
            expect(result._agentNote).toBeUndefined()
        }
    })
})
