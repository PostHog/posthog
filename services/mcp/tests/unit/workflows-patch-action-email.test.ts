import { describe, expect, it, vi } from 'vitest'

import { HogFlowsActionsEmailPartialUpdateBody } from '@/generated/workflows/api'
import { GENERATED_TOOLS } from '@/tools/generated/workflows'
import type { Context } from '@/tools/types'

const FLOW_ID = '00000000-0000-4000-8000-000000000001'

describe('workflows-patch-action-email', () => {
    it.each([
        ['switches to the sandbox sender', { sender: 'sandbox' }],
        ['drops own-sender settings on the switch', { sender: 'sandbox', drop_own_sender_settings: true }],
        ['switches back to an own sender', { sender: 'own', email_patch: { from: { integrationId: 5 } } }],
        ['edits a sandbox step', { email_patch: { subject: 'Welcome' } }],
    ])('%s', async (_name, edit) => {
        const request = vi.fn().mockResolvedValue({ id: FLOW_ID, actions: [] })
        const context = { api: { request }, stateManager: { getProjectId: async () => '42' } } as unknown as Context
        const tool = GENERATED_TOOLS['workflows-patch-action-email']!()

        await tool.handler(context, tool.schema.parse({ id: FLOW_ID, action_id: 'welcome', ...edit }))

        const sent = request.mock.calls[0]![0]
        expect(sent.path).toEqual(`/api/projects/42/hog_flows/${FLOW_ID}/actions/welcome/email/`)
        expect(HogFlowsActionsEmailPartialUpdateBody().strict().parse(sent.body)).toEqual(edit)
    })

    it('asks for an edit when there is none', () => {
        const tool = GENERATED_TOOLS['workflows-patch-action-email']!()

        expect(tool.schema.safeParse({ id: FLOW_ID, action_id: 'welcome' }).success).toBe(false)
    })
})
