import type {
    HogFlowApi,
    HogFlowBatchJobApi,
    HogFlowScheduleApi,
} from 'products/workflows/frontend/generated/api.schemas'

import { StoppableBroadcast, canEditInWizard, canMoveToDraft } from './broadcastsLogic'
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
        ['a custom recipient expression', [trigger(), email('{{ inputs.owner_email }}'), exit], edges, true],
        ['a fixed recipient address', [trigger(), email('team@example.com'), exit], edges, true],
        [
            'a trigger that skips the email',
            [trigger(), email(), exit],
            [{ from: 'trigger_node', to: 'exit_node' }],
            false,
        ],
        ['a second, disconnected exit', [trigger(), email(), exit, { ...exit, id: 'exit_2' }], edges, false],
        [
            'an extra path around the email',
            [trigger(), email(), exit],
            [...edges, { from: 'trigger_node', to: 'exit_node', type: 'continue' }],
            false,
        ],
    ])('opens %s in the wizard: %s', (_, actions, flowEdges, expected) => {
        expect(canEditInWizard(actions, flowEdges)).toBe(expected)
    })

    it.each<
        [
            string,
            HogFlowApi['status'],
            HogFlowScheduleApi['status'][],
            HogFlowBatchJobApi['status'][] | null,
            boolean,
            boolean,
        ]
    >([
        ['a scheduled broadcast', 'active', ['active'], [], false, true],
        ['a recurring broadcast between runs', 'active', ['active'], ['completed'], false, true],
        ['a broadcast whose schedule was paused', 'active', ['paused'], [], false, true],
        ['a broadcast sent right away', 'active', [], ['completed'], false, false],
        ['a broadcast whose launch never finished', 'active', [], [], false, true],
        ['a one-time broadcast that already sent', 'active', ['completed'], ['completed'], false, false],
        ['a one-time schedule that never started a run', 'active', ['completed'], [], false, true],
        ['a workflow with a sent one-time schedule and another', 'active', ['completed', 'active'], [], false, false],
        ['a broadcast mid-send', 'active', ['active'], ['active'], false, false],
        ['a broadcast with an older run still queued', 'active', ['active'], ['completed', 'queued'], false, false],
        ['a broadcast whose runs have not loaded', 'active', ['active'], null, false, false],
        ['a draft', 'draft', ['active'], [], false, false],
        ['a workflow the wizard cannot edit', 'active', ['active'], [], true, false],
    ])('lets %s be stopped: %s', (_, status, scheduleStatuses, jobStatuses, extraStep, expected) => {
        const broadcast: StoppableBroadcast = {
            status,
            schedules: scheduleStatuses.map((scheduleStatus) => ({ status: scheduleStatus })),
            actions: extraStep ? [trigger(), email(), exit, { ...exit, id: 'exit_2' }] : [trigger(), email(), exit],
            edges,
        }
        const jobs = jobStatuses === null ? null : jobStatuses.map((jobStatus) => ({ status: jobStatus }))
        expect(canMoveToDraft(broadcast, jobs)).toBe(expected)
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

    it.each([
        ['a new broadcast', null],
        ['a workflow shaped like a broadcast', { origin_product: null, actions: [trigger(), email(), exit], edges }],
    ])('saves the message category, tracking and UTM tags onto the email step of %s', (_, existing) => {
        const payload = buildBroadcastPayload({
            name: 'Newsletter',
            audienceProperties: [],
            goalEnabled: false,
            conversion: DEFAULT_BROADCAST_CONVERSION,
            email: DEFAULT_BROADCAST_EMAIL,
            emailRateLimit: null,
            emailSettings: {
                messageCategoryId: 'cat-1',
                messageCategoryType: 'marketing',
                trackingEnabled: false,
                utmTagsEnabled: true,
                utmParams: { utm_campaign: '{{ person.properties.plan }}' },
            },
            broadcast: existing as unknown as HogFlowApi | null,
        })

        const emailStep = payload.actions.find((action: any) => action.type === 'function_email')
        expect(emailStep.config).toMatchObject({
            message_category_id: 'cat-1',
            message_category_type: 'marketing',
            tracking_enabled: false,
            utm_tags_enabled: true,
            utm_params: { utm_campaign: '{{ person.properties.plan }}' },
        })
    })
})
