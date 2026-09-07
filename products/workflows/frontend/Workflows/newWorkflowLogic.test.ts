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

    describe('trigger prefill forwarding', () => {
        const triggerJson = '{"type":"batch","filters":{}}'

        it.each([
            ['createWorkflowFromTemplate', { templateId: 'template-1' }],
            ['createEmptyWorkflow', {}],
        ])('%s carries the prefill params onto the new-workflow URL', (action, extraParams) => {
            const logic = newWorkflowLogic()
            logic.mount()
            router.actions.push('/workflows', { trigger: triggerJson, scaffold: 'email' }, { newWorkflow: 'modal' })

            if (action === 'createWorkflowFromTemplate') {
                logic.actions.createWorkflowFromTemplate({ id: 'template-1' } as any)
            } else {
                logic.actions.createEmptyWorkflow()
            }

            expect(router.values.location.pathname).toBe('/workflows/new/workflow')
            expect(router.values.searchParams).toEqual({
                ...extraParams,
                trigger: triggerJson,
                scaffold: 'email',
            })
        })

        it('dismissing the modal drops the prefill params from the URL', () => {
            const logic = newWorkflowLogic()
            logic.mount()
            router.actions.push('/workflows', { trigger: triggerJson, scaffold: 'email' }, { newWorkflow: 'modal' })

            logic.actions.hideNewWorkflowModal()

            expect(router.values.searchParams).not.toHaveProperty('trigger')
            expect(router.values.searchParams).not.toHaveProperty('scaffold')
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
