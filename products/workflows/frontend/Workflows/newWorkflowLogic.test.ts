import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { addProductIntentForCrossSell } from 'lib/utils/product-intents'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { newWorkflowLogic } from './newWorkflowLogic'

jest.mock('lib/utils/product-intents', () => ({
    addProductIntent: jest.fn().mockResolvedValue(null),
    addProductIntentForCrossSell: jest.fn().mockResolvedValue(null),
}))

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

        it('showNewWorkflowModalForPrefill opens the modal in place with the prefill on the URL', () => {
            const logic = newWorkflowLogic()
            logic.mount()
            router.actions.push('/cohorts/6', { page: '1' }, {})

            logic.actions.showNewWorkflowModalForPrefill(triggerJson, ProductKey.COHORTS, 'email')

            expect(logic.values.newWorkflowModalVisible).toBe(true)
            expect(router.values.location.pathname).toBe('/cohorts/6')
            expect(router.values.searchParams).toEqual({ page: '1', trigger: triggerJson, scaffold: 'email' })
        })

        it('registers a Workflows cross-sell intent for the product the prefill came from', () => {
            const logic = newWorkflowLogic()
            logic.mount()

            logic.actions.showNewWorkflowModalForPrefill(triggerJson, ProductKey.COHORTS, 'email')

            expect(addProductIntentForCrossSell).toHaveBeenCalledWith({
                from: ProductKey.COHORTS,
                to: ProductKey.WORKFLOWS,
                intent_context: ProductIntentContext.WORKFLOW_CREATED,
            })
        })

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
