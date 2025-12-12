import { resetContext } from 'kea'
import { expectLogic, partial, testUtilsPlugin } from 'kea-test-utils'

import { uuid } from 'lib/utils'

import { initKeaTests } from '~/test/init'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowAction } from '../types'
import { getWaitUntilTimeWindowDescription, stepWaitUntilTimeWindowLogic } from './stepWaitUntilTimeWindowLogic'

describe('stepWaitUntilTimeWindowLogic', () => {
    let logic: ReturnType<typeof stepWaitUntilTimeWindowLogic.build>

    beforeEach(() => {
        initKeaTests()

        resetContext({
            plugins: [testUtilsPlugin],
        })

        workflowLogic.mount()

        logic = stepWaitUntilTimeWindowLogic({ workflowLogicProps: workflowLogic.props })
        logic.mount()
    })

    const setupInitialAction = async (initialDescription: string): Promise<HogFlowAction> => {
        const action = {
            id: `wait_action_${uuid()}`,
            type: 'wait_until_time_window',
            name: 'Wait until time window',
            description: initialDescription,
            config: { day: 'weekday', time: ['09:00', '17:00'], timezone: 'UTC' },
            created_at: Date.now(),
            updated_at: Date.now(),
        } as HogFlowAction

        await expectLogic(workflowLogic, () => {
            workflowLogic.actions.setWorkflowInfo({
                actions: [...workflowLogic.values.workflow.actions, action],
            })
        }).toDispatchActions(['setWorkflowInfo'])

        await expectLogic(workflowLogic).toMatchValues({
            workflow: partial({
                actions: expect.arrayContaining([expect.objectContaining({ description: initialDescription })]),
            }),
        })

        return action
    }
    it('should update the description when day is changed', async () => {
        const initialDesc = getWaitUntilTimeWindowDescription('weekday', ['09:00', '17:00'], 'UTC')
        const action = await setupInitialAction(initialDesc)

        await expectLogic(logic, () => {
            logic.actions.partialSetWaitUntilTimeWindowConfig(action.id, { day: 'weekend' })
        })
            .toDispatchActions(['partialSetWorkflowActionConfig'])
            .toFinishListeners()

        await expectLogic(logic).toMatchValues({
            workflow: partial({
                actions: expect.arrayContaining([
                    expect.objectContaining({
                        description: 'Wait until weekends between 09:00 and 17:00 (UTC).',
                    }),
                ]),
            }),
        })
    })

    it('should update the description when time is changed', async () => {
        const initialDesc = getWaitUntilTimeWindowDescription('weekday', ['09:00', '17:00'], 'UTC')
        const action = await setupInitialAction(initialDesc)

        await expectLogic(logic, () => {
            logic.actions.partialSetWaitUntilTimeWindowConfig(action.id, { time: ['10:00', '18:00'] })
        })
            .toDispatchActions(['partialSetWorkflowActionConfig'])
            .toFinishListeners()

        await expectLogic(logic).toMatchValues({
            workflow: partial({
                actions: expect.arrayContaining([
                    expect.objectContaining({
                        description: 'Wait until weekdays between 10:00 and 18:00 (UTC).',
                    }),
                ]),
            }),
        })
    })

    it('should update the description when timezone is changed', async () => {
        const initialDesc = getWaitUntilTimeWindowDescription('weekday', ['09:00', '17:00'], 'UTC')
        const action = await setupInitialAction(initialDesc)

        await expectLogic(logic, () => {
            logic.actions.partialSetWaitUntilTimeWindowConfig(action.id, { timezone: 'America/New_York' })
        })
            .toDispatchActions(['partialSetWorkflowActionConfig'])
            .toFinishListeners()

        await expectLogic(logic).toMatchValues({
            workflow: partial({
                actions: expect.arrayContaining([
                    expect.objectContaining({
                        description: 'Wait until weekdays between 09:00 and 17:00 (America/New_York).',
                    }),
                ]),
            }),
        })
    })

    it('should not update the description when the description is customized', async () => {
        const customDescription = 'Custom description, dont delete me pls :('
        const action = await setupInitialAction(customDescription)

        await expectLogic(logic, () => {
            logic.actions.partialSetWaitUntilTimeWindowConfig(action.id, { day: 'weekend' })
        })
            .toDispatchActions(['partialSetWorkflowActionConfig'])
            .toFinishListeners()

        await expectLogic(logic).toMatchValues({
            workflow: partial({
                actions: expect.arrayContaining([expect.objectContaining({ description: customDescription })]),
            }),
        })
    })
})
