import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { newWorkflowLogic } from './newWorkflowLogic'

describe('newWorkflowLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    describe('urlToAction', () => {
        it('opens modal when navigating to /workflows with #newWorkflow hash param', async () => {
            const logic = newWorkflowLogic()
            logic.mount()

            await expectLogic(logic, () => {
                router.actions.push('/workflows', {}, { newWorkflow: 'modal' })
            })
                .toDispatchActions(['showNewWorkflowModal'])
                .toMatchValues({
                    newWorkflowModalVisible: true,
                })
        })

        it('opens modal when navigating to /workflows/:tab with #newWorkflow hash param', async () => {
            const logic = newWorkflowLogic()
            logic.mount()

            await expectLogic(logic, () => {
                router.actions.push('/workflows/library', {}, { newWorkflow: 'modal' })
            })
                .toDispatchActions(['showNewWorkflowModal'])
                .toMatchValues({
                    newWorkflowModalVisible: true,
                })
        })

        it('does not open modal when hash param is missing', async () => {
            const logic = newWorkflowLogic()
            logic.mount()

            await expectLogic(logic, () => {
                router.actions.push('/workflows', {}, {})
            }).toNotHaveDispatchedActions(['showNewWorkflowModal'])

            expect(logic.values.newWorkflowModalVisible).toBe(false)
        })
    })

    describe('actionToUrl', () => {
        it('adds newWorkflow hash param when showing modal', () => {
            const logic = newWorkflowLogic()
            logic.mount()

            router.actions.push('/workflows', {}, {})
            logic.actions.showNewWorkflowModal()

            expect(router.values.hashParams).toHaveProperty('newWorkflow', 'modal')
        })

        it('removes newWorkflow hash param when hiding modal', () => {
            const logic = newWorkflowLogic()
            logic.mount()

            router.actions.push('/workflows', {}, { newWorkflow: 'modal' })
            logic.actions.hideNewWorkflowModal()

            expect(router.values.hashParams).not.toHaveProperty('newWorkflow')
        })
    })
})
