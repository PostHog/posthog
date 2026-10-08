import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HogFlow } from './hogflows/types'
import { NEW_WORKFLOW, workflowLogic } from './workflowLogic'
import { type WorkflowTriggerConfig } from './workflowTriggerPrefill'

const template: HogFlow = {
    ...NEW_WORKFLOW,
    id: 'template-1',
    name: 'Welcome email',
    trigger: { type: 'event', filters: { events: [{ id: '$pageview', type: 'events' }] } },
    actions: NEW_WORKFLOW.actions.map((action) =>
        action.type === 'trigger'
            ? { ...action, config: { type: 'event', filters: { events: [{ id: '$pageview', type: 'events' }] } } }
            : action
    ),
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
    })
})
