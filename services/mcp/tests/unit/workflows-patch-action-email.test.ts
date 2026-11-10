import { describe, expect, it } from 'vitest'

import { WorkflowActionEmailPatchSchema } from '@/schema/tool-inputs'

const STEP = { id: '00000000-0000-4000-8000-000000000001', action_id: 'welcome' }

describe('workflows-patch-action-email input', () => {
    it.each([
        ['switches to the sandbox sender', { sender: 'sandbox' }],
        ['drops own-sender settings on the switch', { sender: 'sandbox', drop_own_sender_settings: true }],
        ['switches back to an own sender', { sender: 'own', email_patch: { from: { integrationId: 5 } } }],
        ['edits a sandbox step', { email_patch: { subject: 'Welcome' } }],
    ])('keeps the edit when it %s', (_name, edit) => {
        expect(WorkflowActionEmailPatchSchema.parse({ ...STEP, ...edit })).toEqual({ ...STEP, ...edit })
    })

    it('asks for an edit when there is none', () => {
        expect(WorkflowActionEmailPatchSchema.safeParse(STEP).success).toBe(false)
    })
})
