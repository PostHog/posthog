import { describe, expect, it } from 'vitest'

import { HogFlowsActionsEmailPartialUpdateBody } from '@/generated/workflows/api'
import { GENERATED_TOOLS } from '@/tools/generated/workflows'
import type { Context } from '@/tools/types'

const FLOW_ID = '00000000-0000-4000-8000-000000000001'
const PROJECT_ID = '42'

type Step = { id: string; type: string; email: Record<string, unknown> }

// Stands in for the email patch endpoint: it accepts only the body the real API's schema accepts, and
// applies the sender switch to the stored step.
function emailEndpoint(step: Step): { stored: Step; context: Context } {
    const stored = { ...step, email: { ...step.email } }
    const request = async ({
        method,
        path,
        body,
    }: {
        method: string
        path: string
        body: unknown
    }): Promise<unknown> => {
        if (
            method !== 'PATCH' ||
            path !== `/api/projects/${PROJECT_ID}/hog_flows/${FLOW_ID}/actions/${step.id}/email/`
        ) {
            throw new Error(`No route for ${method} ${path}`)
        }
        const edit = HogFlowsActionsEmailPartialUpdateBody().strict().parse(body)
        if (edit.sender === 'sandbox') {
            if (stored.email.replyTo && !edit.drop_own_sender_settings) {
                throw new Error("The sandbox sender can't keep these settings: replyTo.")
            }
            stored.type = 'email_sandbox'
            delete stored.email.replyTo
            delete stored.email.from
        }
        if (edit.sender === 'own') {
            stored.type = 'function_email'
        }
        Object.assign(stored.email, edit.email_patch ?? {})
        return { id: FLOW_ID, actions: [{ id: stored.id, type: stored.type, config: {} }] }
    }
    const context = { api: { request }, stateManager: { getProjectId: async () => PROJECT_ID } } as unknown as Context
    return { stored, context }
}

async function patchEmail(context: Context, edit: Record<string, unknown>): Promise<unknown> {
    const tool = GENERATED_TOOLS['workflows-patch-action-email']!()
    return tool.handler(context, tool.schema.parse({ id: FLOW_ID, action_id: 'welcome', ...edit }))
}

const OWN_STEP: Step = { id: 'welcome', type: 'function_email', email: { subject: 'Hi', from: { integrationId: 5 } } }
const SANDBOX_STEP: Step = { id: 'welcome', type: 'email_sandbox', email: { subject: 'Hi' } }

describe('workflows-patch-action-email', () => {
    it.each([
        ['moves a step to the sandbox sender', OWN_STEP, { sender: 'sandbox' }, 'email_sandbox', { subject: 'Hi' }],
        [
            'drops own-sender settings when asked',
            { ...OWN_STEP, email: { ...OWN_STEP.email, replyTo: 'help@example.com' } },
            { sender: 'sandbox', drop_own_sender_settings: true },
            'email_sandbox',
            { subject: 'Hi' },
        ],
        [
            'moves a sandbox step back to an own sender',
            SANDBOX_STEP,
            { sender: 'own', email_patch: { from: { integrationId: 7 } } },
            'function_email',
            { subject: 'Hi', from: { integrationId: 7 } },
        ],
        [
            'edits a sandbox step',
            SANDBOX_STEP,
            { email_patch: { subject: 'Welcome' } },
            'email_sandbox',
            { subject: 'Welcome' },
        ],
    ])('%s', async (_name, step, edit, type, email) => {
        const { stored, context } = emailEndpoint(step)

        await patchEmail(context, edit)

        expect(stored).toEqual({ id: 'welcome', type, email })
    })

    it('leaves the step alone when the switch would lose settings', async () => {
        const step = { ...OWN_STEP, email: { ...OWN_STEP.email, replyTo: 'help@example.com' } }
        const { stored, context } = emailEndpoint(step)

        await expect(patchEmail(context, { sender: 'sandbox' })).rejects.toThrow("can't keep these settings")
        expect(stored).toEqual(step)
    })

    it('asks for an edit when there is none', () => {
        const tool = GENERATED_TOOLS['workflows-patch-action-email']!()

        expect(tool.schema.safeParse({ id: FLOW_ID, action_id: 'welcome' }).success).toBe(false)
    })
})
