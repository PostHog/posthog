import { resetContext } from 'kea'
import { expectLogic, partial, testUtilsPlugin } from 'kea-test-utils'

import { uuid } from 'lib/utils'

import { initKeaTests } from '~/test/init'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowAction } from '../types'
import { getDelayDescription, stepDelayLogic } from './stepDelayLogic'

describe('stepDelayLogic', () => {
    let sdLogic: ReturnType<typeof stepDelayLogic.build>

    beforeEach(() => {
        initKeaTests()

        resetContext({
            plugins: [testUtilsPlugin],
        })

        workflowLogic.mount()

        sdLogic = stepDelayLogic({ workflowLogicProps: workflowLogic.props })
        sdLogic.mount()
    })

    const setupInitialDelayAction = async (initialDescription: string): Promise<HogFlowAction> => {
        const delayAction = {
            id: `delay_action_${uuid()}`,
            type: 'delay',
            name: 'Delay',
            description: initialDescription,
            config: { delay_duration: '10m' },
            created_at: Date.now(),
            updated_at: Date.now(),
        } as HogFlowAction

        await expectLogic(workflowLogic, () => {
            workflowLogic.actions.setWorkflowInfo({
                actions: [...workflowLogic.values.workflow.actions, delayAction],
            })
        }).toDispatchActions(['setWorkflowInfo'])

        await expectLogic(workflowLogic).toMatchValues({
            workflow: partial({
                actions: expect.arrayContaining([expect.objectContaining({ description: initialDescription })]),
            }),
        })

        return delayAction
    }

    it('should update the description when the duration is changed', async () => {
        const delayAction = await setupInitialDelayAction(getDelayDescription('10m'))

        await expectLogic(sdLogic, () => {
            sdLogic.actions.setDelayWorkflowActionConfig(delayAction.id, { delay_duration: '5m' })
        })
            .toDispatchActions(['setWorkflowActionConfig'])
            .toFinishListeners()

        await expectLogic(sdLogic).toMatchValues({
            workflow: partial({
                actions: expect.arrayContaining([expect.objectContaining({ description: 'Wait for 5 minutes.' })]),
            }),
        })
    })

    it('should not update the description when the description is customized', async () => {
        const customDescription = 'Custom description, dont delete me pls :('
        const delayAction = await setupInitialDelayAction(customDescription)

        await expectLogic(sdLogic, () => {
            sdLogic.actions.setDelayWorkflowActionConfig(delayAction.id, { delay_duration: '5m' })
        })
            .toDispatchActions(['setWorkflowActionConfig'])
            .toFinishListeners()

        await expectLogic(sdLogic).toMatchValues({
            workflow: partial({
                actions: expect.arrayContaining([expect.objectContaining({ description: customDescription })]),
            }),
        })
    })
})
