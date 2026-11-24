import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

// Registers the product trigger tiles, as StepTrigger does in the editor.
import './hogflows/registry/triggers'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { MockResolverInfo } from '~/mocks/utils'
import { initKeaTests } from '~/test/init'

import { draftMessage } from '../MessageAudience/messageDrafts'
import { EVENT_TRIGGER_WITH_NO_EVENT } from './emailTemplateWorkflowPrefill'
import { HogFlow } from './hogflows/types'
import { EXIT_NODE_ID, NEW_WORKFLOW, TRIGGER_NODE_ID, workflowLogic } from './workflowLogic'
import type { WorkflowTriggerConfig } from './workflowTriggerPrefill'

const template: HogFlow = {
    ...NEW_WORKFLOW,
    id: 'template-1',
    name: 'Welcome email',
    trigger_masking: { ttl: 1800, hash: '{person.id}', bytecode: ['_H', 1], threshold: null },
    trigger: { type: 'event', filters: { events: [{ id: '$pageview', type: 'events' }] } },
    actions: [
        ...NEW_WORKFLOW.actions.map((action): HogFlow['actions'][number] =>
            action.type === 'trigger'
                ? { ...action, config: { type: 'event', filters: { events: [{ id: '$pageview', type: 'events' }] } } }
                : action
        ),
        {
            id: 'welcome_delay',
            type: 'delay',
            name: 'Wait before welcoming',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: { delay_duration: '5m' },
        },
    ],
    edges: [
        { from: TRIGGER_NODE_ID, to: 'welcome_delay', type: 'continue' },
        { from: 'welcome_delay', to: EXIT_NODE_ID, type: 'continue' },
    ],
}

const LINK_OPENED = 'workflow email template link opened'

function linkOpenedCalls(captureSpy: jest.SpyInstance): unknown[][] {
    return captureSpy.mock.calls.filter(([event]) => event === LINK_OPENED)
}

const linkedEventTrigger: WorkflowTriggerConfig = {
    type: 'event',
    filters: { events: [{ id: 'user_signed_up', type: 'events' }] },
}

const linkedInternalEventTrigger: WorkflowTriggerConfig = {
    type: 'internal-event',
    filters: { source: 'internal-events', events: [{ id: '$insight_alert_firing', type: 'internal_events' }] },
}

const linkedAccountPropertyTrigger: WorkflowTriggerConfig = {
    type: 'event',
    filters: { events: [{ id: '$account_custom_property_changed', type: 'events' }] },
}

const linkedMixedEventTrigger: WorkflowTriggerConfig = {
    type: 'event',
    filters: {
        events: [
            { id: 'user_signed_up', type: 'events' },
            { id: '$account_custom_property_changed', type: 'events' },
        ],
    },
}

const TRANSACTIONAL_CATEGORY_ID = '00000000-0000-4000-8000-0000000000c1'
const MARKETING_CATEGORY_ID = '00000000-0000-4000-8000-0000000000c2'
const CATEGORY_TYPES: Record<string, string> = {
    [TRANSACTIONAL_CATEGORY_ID]: 'transactional',
    [MARKETING_CATEGORY_ID]: 'marketing',
}

// Like the real endpoint, answers only for a category of the environment it is asked in.
const categoriesIn = (environmentId: number): Record<string, (req: MockResolverInfo) => [number, object]> => ({
    '/api/projects/:team_id/messaging_categories/:id/': (req: MockResolverInfo) =>
        req.params.team_id === String(environmentId) && CATEGORY_TYPES[req.params.id as string]
            ? [200, { id: req.params.id, category_type: CATEGORY_TYPES[req.params.id as string] }]
            : [404, { detail: 'Not found.' }],
})

const transactionalTemplate = {
    id: '00000000-0000-4000-8000-000000000001',
    name: 'Order receipt',
    description: '',
    sensitive: false,
    transactional_hog_flow_id: '00000000-0000-4000-8000-0000000000f1',
    message_category: TRANSACTIONAL_CATEGORY_ID,
    content: {
        templating: 'liquid',
        email: {
            from: { integrationId: 42, email: 'orders@example.com', name: '{{ variables.store_name }}' },
            replyTo: 'help@example.com',
            subject: 'Your order {{ variables.order_id }}',
            preheader: 'Thanks for your order',
            html: '<p>{% if variables.coupon %}Use {{ variables.coupon | upcase }}{% endif %}</p>',
            text: 'Order {{variables.order_id}}. Set variables.order_id in the send call.',
            design: { body: { rows: [{ values: { html: '<b>{{ variables.order_id }}</b>' } }] } },
        },
    },
    draft_content: {
        templating: 'liquid',
        email: { subject: 'Unpublished subject', html: '<p>Draft</p>', text: 'Draft' },
    },
}

describe('workflowLogic pages opened from a link or a template', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flow_templates/:id/': template,
            },
        })
    })

    it.each([
        ['an event trigger keeps the template frequency limit', linkedEventTrigger, template.trigger_masking],
        ['a trigger of another type clears the template frequency limit', linkedInternalEventTrigger, null],
        ['another event trigger tile clears the template frequency limit', linkedAccountPropertyTrigger, null],
        ['a later event of another trigger tile clears the template frequency limit', linkedMixedEventTrigger, null],
    ])('opens a template on the trigger passed in the link: %s', async (_, linkedTrigger, expectedMasking) => {
        const logic = workflowLogic({
            id: 'new',
            templateId: template.id,
            triggerPrefill: JSON.stringify(linkedTrigger),
        })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])

        const triggerAction = logic.values.workflow.actions.find((action) => action.type === 'trigger')
        expect(triggerAction?.config).toEqual(linkedTrigger)
        expect(logic.values.workflow.trigger).toEqual(linkedTrigger)
        expect(logic.values.workflow.name).toEqual('Welcome email')
        expect(logic.values.workflow.actions.filter((action) => action.type !== 'trigger')).toEqual(
            template.actions.filter((action) => action.type !== 'trigger')
        )
        expect(logic.values.workflow.edges).toEqual(template.edges)
        expect(logic.values.workflow.trigger_masking).toEqual(expectedMasking)
    })

    it.each([
        { case: 'a blank new workflow', props: {}, id: 'new', name: 'New workflow', version: 1 },
        {
            case: 'a copy of a template',
            props: { templateId: template.id },
            id: undefined,
            name: template.name,
            version: 1,
        },
        {
            case: 'the template itself',
            props: { editTemplateId: template.id },
            id: template.id,
            name: template.name,
            version: 7,
        },
    ])('opens $case on a new workflow page', async ({ case: _, props, ...expected }) => {
        useMocks({
            get: { '/api/projects/:team_id/hog_flow_templates/:id/': { ...template, version: 7, status: 'active' } },
        })
        const logic = workflowLogic({ id: 'new', ...props })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        const { id, name, status, version } = logic.values.workflow
        expect({ id, name, status, version }).toEqual({ ...expected, status: 'draft' })
    })

    it('saves a workflow opened from a link with the sender that can send when the project default stopped', async () => {
        const created: Partial<HogFlow>[] = []
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': {
                    results: [
                        { id: 1, kind: 'email', config: { verified: true, ses_sending_status: 'failed' } },
                        { id: 2, kind: 'email', config: { verified: true } },
                    ],
                    next: null,
                },
            },
            post: {
                '/api/projects/:team_id/hog_flows/': async ({ request }) => {
                    const body = (await request.json()) as Partial<HogFlow>
                    created.push(body)
                    return [201, { ...body, id: 'flow-1' }]
                },
            },
        })
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            workflows_config: { default_email_integration_id: 1 },
        } as any)
        const logic = workflowLogic({
            id: 'new',
            triggerPrefill: JSON.stringify(linkedEventTrigger),
            emailPrefill: JSON.stringify(draftMessage({ kind: 'issue_hit' })),
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.saveWorkflow(logic.values.workflow)
        await expectLogic(logic).toFinishAllListeners()

        const email = created[0]?.actions?.find((action) => action.type === 'function_email')
        expect((email?.config as any)?.inputs.email.value.from).toEqual({ integrationId: 2 })
    })

    it('keeps one editor per saved workflow and per template', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': ({ params }: MockResolverInfo) => [
                    200,
                    { ...NEW_WORKFLOW, id: params.id, name: `Saved ${params.id}` },
                ],
            },
        })
        const opened = [{ id: 'wf-a' }, { id: 'wf-b' }, { id: 'new' }, { id: 'new', templateId: template.id }]
        const logics = opened.map((props) => workflowLogic(props))
        for (const logic of logics) {
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
        }
        logics[0].actions.setWorkflowValue('name', 'Renamed a')

        expect(logics.map((logic) => logic.values.workflow.name)).toEqual([
            'Renamed a',
            'Saved wf-b',
            'New workflow',
            template.name,
        ])
        expect(logics.map((logic) => logic.values.logicProps)).toEqual(opened)
        expect(workflowLogic({ id: 'wf-a' }).values.workflow.name).toBe('Renamed a')
    })

    it('opens an event workflow that sends the published email of a transactional template from an environment, with its variables read from the event', async () => {
        const environmentId = MOCK_DEFAULT_TEAM.id + 1
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: environmentId })
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_templates/:id/': (req: MockResolverInfo) =>
                    req.params.team_id === String(environmentId) && req.params.id === transactionalTemplate.id
                        ? [200, transactionalTemplate]
                        : [404, { detail: 'Not found.' }],
                ...categoriesIn(environmentId),
            },
        })
        const logic = workflowLogic({
            id: 'new',
            triggerPrefill: JSON.stringify(EVENT_TRIGGER_WITH_NO_EVENT),
            messageTemplateId: transactionalTemplate.id,
        })
        const captureSpy = jest.spyOn(posthog, 'capture')
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])

        expect(linkOpenedCalls(captureSpy)).toEqual([
            [LINK_OPENED, { template_id: transactionalTemplate.id, outcome: 'copied' }],
        ])
        captureSpy.mockRestore()
        const { workflow } = logic.values
        const [trigger, email, exit] = workflow.actions
        expect(workflow.name).toBe('Order receipt')
        expect(trigger.config).toEqual(EVENT_TRIGGER_WITH_NO_EVENT)
        expect(workflow.trigger_masking ?? null).toBeNull()
        expect(exit.type).toBe('exit')
        expect(workflow.edges).toEqual([
            { from: trigger.id, to: email.id, type: 'continue' },
            { from: email.id, to: exit.id, type: 'continue' },
        ])
        expect(email).toMatchObject({
            type: 'function_email',
            name: 'Order receipt',
            config: {
                template_id: 'template-email',
                message_category_type: 'transactional',
                inputs: {
                    email: {
                        templating: 'liquid',
                        value: {
                            from: {
                                integrationId: 42,
                                email: 'orders@example.com',
                                name: '{{ event.properties.store_name }}',
                            },
                            replyTo: 'help@example.com',
                            subject: 'Your order {{ event.properties.order_id }}',
                            preheader: 'Thanks for your order',
                            html: '<p>{% if event.properties.coupon %}Use {{ event.properties.coupon | upcase }}{% endif %}</p>',
                            text: 'Order {{event.properties.order_id}}. Set variables.order_id in the send call.',
                            design: {
                                body: { rows: [{ values: { html: '<b>{{ event.properties.order_id }}</b>' } }] },
                            },
                            to: { email: '{{ person.properties.email }}', name: '' },
                        },
                    },
                },
            },
        })
    })

    it.each<[string, WorkflowTriggerConfig, () => [number, Record<string, unknown>], string | null]>([
        [
            'the template no longer exists',
            EVENT_TRIGGER_WITH_NO_EVENT,
            () => [404, { detail: 'Not found.' }],
            'load_failed',
        ],
        [
            'the template is sensitive, as its values would come from a stored event',
            EVENT_TRIGGER_WITH_NO_EVENT,
            () => [200, { ...transactionalTemplate, sensitive: true }],
            'sensitive',
        ],
        [
            'the template is not transactional, as the step would send past marketing opt-outs',
            EVENT_TRIGGER_WITH_NO_EVENT,
            () => [200, { ...transactionalTemplate, transactional_hog_flow_id: null }],
            'not_transactional',
        ],
        [
            'the template is in a marketing category, which the send API refuses as well',
            EVENT_TRIGGER_WITH_NO_EVENT,
            () => [200, { ...transactionalTemplate, message_category: MARKETING_CATEGORY_ID }],
            'marketing_category',
        ],
        [
            'the link names an internal event trigger, which has no person to send to',
            linkedInternalEventTrigger,
            () => [200, transactionalTemplate],
            null,
        ],
    ])('opens the linked workflow without an email step when %s', async (_, trigger, respond, outcome) => {
        useMocks({
            get: { '/api/projects/:team_id/messaging_templates/:id/': respond, ...categoriesIn(MOCK_DEFAULT_TEAM.id) },
        })
        const logic = workflowLogic({
            id: 'new',
            triggerPrefill: JSON.stringify(trigger),
            messageTemplateId: transactionalTemplate.id,
        })
        const captureSpy = jest.spyOn(posthog, 'capture')
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])

        expect(linkOpenedCalls(captureSpy)).toEqual(
            outcome ? [[LINK_OPENED, { template_id: transactionalTemplate.id, outcome }]] : []
        )
        captureSpy.mockRestore()
        expect(logic.values.workflow.actions.map((action) => action.type)).toEqual(['trigger', 'exit'])
        expect(logic.values.workflow.actions[0].config).toEqual(trigger)
    })
})
