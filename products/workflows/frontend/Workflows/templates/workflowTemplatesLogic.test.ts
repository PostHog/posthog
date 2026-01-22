import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { workflowTemplatesLogic } from './workflowTemplatesLogic'

describe('workflowTemplatesLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    describe('urlToAction', () => {
        it('sets template filter based on searchParams', async () => {
            const logic = workflowTemplatesLogic()
            logic.mount()

            await expectLogic(logic, () => {
                router.actions.push('/workflows', { templateFilter: 'test search' }, {})
            })
                .toDispatchActions(['setTemplateFilter'])
                .toMatchValues({
                    templateFilter: 'test search',
                })
        })
    })

    describe('actionToUrl', () => {
        it('sets URL based on template filter', () => {
            const logic = workflowTemplatesLogic()
            logic.mount()

            router.actions.push('/workflows', {}, {})
            logic.actions.setTemplateFilter('my filter')

            expect(router.values.searchParams).toHaveProperty('templateFilter', 'my filter')
        })
    })
})
