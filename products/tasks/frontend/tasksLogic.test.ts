import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { tasksLogic } from './tasksLogic'

jest.mock('lib/api')

describe('tasksLogic', () => {
    let logic: ReturnType<typeof tasksLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api.tasks, 'list').mockResolvedValue({ results: [] })
        jest.spyOn(api, 'get').mockResolvedValue({ results: [] })
        logic = tasksLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.clearAllMocks()
    })

    describe('URL handling', () => {
        it('handles tab switching', async () => {
            await expectLogic(logic, () => {
                logic.actions.setActiveTab('kanban')
            })
                .toMatchValues({
                    activeTab: 'kanban',
                })
                .toFinishAllListeners()

            expect(router.values.searchParams).toEqual(
                expect.objectContaining({
                    tab: 'kanban',
                })
            )
        })

        it('handles invalid tab values by defaulting to dashboard', async () => {
            await expectLogic(logic, () => {
                router.actions.push('/tasks?tab=invalid')
            })
                .toMatchValues({
                    activeTab: 'dashboard',
                })
                .toFinishAllListeners()

            expect(router.values.searchParams.tab).toBeUndefined()
        })
    })
})
