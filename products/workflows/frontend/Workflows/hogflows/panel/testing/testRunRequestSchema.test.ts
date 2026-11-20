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
    name: 'Welcome series',
    status: 'active',
    trigger: { type: 'event', filters: { events: [{ id: '$pageview', name: '$pageview', type: 'events', order: 0 }] } },
    actions: [
        {
            id: 'trigger_node',
            name: 'Trigger',
            type: 'trigger',
            config: {
                type: 'event',
                filters: { events: [{ id: '$pageview', name: '$pageview', type: 'events', order: 0 }] },
            },
        },
        {
            id: 'action_email_1',
            name: 'Welcome email',
            type: 'function_email',
            config: {
                template_id: 'template-email',
                inputs: {
                    email: {
                        templating: 'liquid',
                        value: {
                            to: { email: '{{ person.properties.email }}', name: '' },
                            from: { email: 'hello@example.com', name: 'Example' },
                            subject: 'Welcome',
                            text: 'Welcome aboard.',
                            html: '',
                        },
                    },
                },
            },
        },
    ],
    edges: [{ from: 'trigger_node', to: 'action_email_1', type: 'continue' }],
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
