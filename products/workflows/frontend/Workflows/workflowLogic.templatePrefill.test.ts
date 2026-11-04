// Registers the product trigger tiles, as StepTrigger does in the editor.
import './hogflows/registry/triggers'

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HogFlow } from './hogflows/types'
import { EXIT_NODE_ID, NEW_WORKFLOW, TRIGGER_NODE_ID, workflowLogic } from './workflowLogic'
import { type WorkflowTriggerConfig } from './workflowTriggerPrefill'

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

describe('workflowLogic template links', () => {
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
})
