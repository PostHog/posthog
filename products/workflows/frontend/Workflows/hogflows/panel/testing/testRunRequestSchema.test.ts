import { HogFlowsInvocationsCreateBody } from 'products/workflows/frontend/generated/api.zod'

const savedWorkflowWithoutWarnings = {
    id: '0190c1b2-1234-7abc-8def-0123456789ab',
    version: 1,
    created_at: '2026-01-01T00:00:00Z',
    created_by: {
        id: 1,
        uuid: '0190c1b2-5678-7abc-8def-0123456789ab',
        email: 'author@example.com',
        hedgehog_config: null,
    },
    updated_at: '2026-01-01T00:00:00Z',
    trigger: {},
    actions: [],
    edges: [],
    abort_action: null,
    billable_action_types: [],
    schedules: [],
    user_access_level: null,
    draft_updated_at: null,
    action_redirects: null,
    email_sending_paused_at: null,
    email_sending_paused_reason: '',
    email_sending_paused_by: '',
    email_sending_pause_requires_support: false,
    email_sending_resumed_at: null,
    last_run: null,
}

describe('test run request schema', () => {
    it('accepts a configuration override without the response-only warnings', () => {
        const result = HogFlowsInvocationsCreateBody.safeParse({
            configuration: savedWorkflowWithoutWarnings,
            globals: {},
        })

        expect(result.error?.issues ?? []).toEqual([])
        expect(result.success).toBe(true)
    })
})
