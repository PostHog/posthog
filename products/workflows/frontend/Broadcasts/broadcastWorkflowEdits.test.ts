import type { HogFlowApi } from 'products/workflows/frontend/generated/api.schemas'

import { canEditInWizard } from './broadcastsLogic'
import { DEFAULT_BROADCAST_CONVERSION, DEFAULT_BROADCAST_EMAIL, buildBroadcastPayload } from './broadcastWizardLogic'

const trigger = (filters: Record<string, any> = { properties: [] }): Record<string, any> => ({
    id: 'trigger_node',
    type: 'trigger',
    name: 'Audience',
    config: { type: 'batch', filters },
})
const email = (to = '{{ person.properties.email }}'): Record<string, any> => ({
    id: 'email_1',
    type: 'function_email',
    name: 'Email',
    on_error: 'continue',
    config: { template_id: 'template-email', inputs: { email: { value: { to: { email: to } } }, extra: { value: 1 } } },
})
const exit = { id: 'exit_node', type: 'exit', name: 'Exit', config: {} }
const edges = [
    { from: 'trigger_node', to: 'email_1', type: 'continue' },
    { from: 'email_1', to: 'exit_node', type: 'continue' },
]

describe('broadcast edits to broadcast-shaped workflows', () => {
    it.each([
        ['a person audience sent to each person', [trigger(), email(), exit], edges, true],
        ['an account audience', [trigger({ audience_type: 'accounts', properties: [] }), email(), exit], edges, false],
        ['a custom recipient expression', [trigger(), email('{{ inputs.owner_email }}'), exit], edges, false],
        [
            'a trigger that skips the email',
            [trigger(), email(), exit],
            [{ from: 'trigger_node', to: 'exit_node' }],
            false,
        ],
        [
            'an extra path around the email',
            [trigger(), email(), exit],
            [...edges, { from: 'trigger_node', to: 'exit_node', type: 'continue' }],
            false,
        ],
    ])('opens %s in the wizard: %s', (_, actions, flowEdges, expected) => {
        expect(canEditInWizard(actions, flowEdges)).toBe(expected)
    })

    it('saves the audience and email into the existing steps without replacing them', () => {
        const existing = {
            origin_product: null,
            actions: [trigger({ properties: [], cohort_hint: 'kept' }), email(), exit],
            edges,
        } as unknown as HogFlowApi

        const payload = buildBroadcastPayload({
            name: 'Renamed',
            audienceProperties: [{ key: 'plan', value: 'pro', operator: 'exact', type: 'person' }] as any,
            goalEnabled: false,
            conversion: DEFAULT_BROADCAST_CONVERSION,
            email: { ...DEFAULT_BROADCAST_EMAIL, subject: 'New subject' },
            emailRateLimit: null,
            broadcast: existing,
        })

        expect(payload).not.toHaveProperty('origin_product')
        expect(payload.edges).toEqual(edges)
        expect(payload.actions.map((action: any) => [action.id, action.name])).toEqual([
            ['trigger_node', 'Audience'],
            ['email_1', 'Email'],
            ['exit_node', 'Exit'],
        ])
        expect(payload.actions[0].config.filters).toEqual({
            properties: [{ key: 'plan', value: 'pro', operator: 'exact', type: 'person' }],
            cohort_hint: 'kept',
        })
        expect(payload.actions[1].on_error).toBe('continue')
        expect(payload.actions[1].config.inputs.extra).toEqual({ value: 1 })
        expect(payload.actions[1].config.inputs.email.value.subject).toBe('New subject')
    })
})
