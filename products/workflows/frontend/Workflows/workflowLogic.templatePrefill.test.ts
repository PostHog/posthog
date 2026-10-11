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

const linkedTrigger: WorkflowTriggerConfig = {
    type: 'event',
    filters: { events: [{ id: 'user_signed_up', type: 'events' }] },
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

    it('opens a template on the trigger passed in the link', async () => {
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
    })
})
