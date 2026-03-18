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

    describe('availableTags', () => {
        it('includes tags from global and own-team templates', async () => {
            const logic = workflowTemplatesLogic()
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.loadWorkflowTemplatesSuccess([
                    { id: 'global-1', name: 'Official', scope: 'global', tags: ['official-a', 'official-b'] } as any,
                    { id: 'team-1', name: 'Team', scope: 'team', tags: ['team-only'] } as any,
                ])
            }).toMatchValues({
                availableTags: ['official-a', 'official-b', 'team-only'],
            })
        })

        it('returns empty array when no templates have tags', async () => {
            const logic = workflowTemplatesLogic()
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.loadWorkflowTemplatesSuccess([
                    { id: 'global-1', name: 'Official', scope: 'global', tags: [] } as any,
                ])
            }).toMatchValues({
                availableTags: [],
            })
        })
    })
})
