import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { logsViewerModalLogic } from './logsViewerModalLogic'

describe('logsViewerModalLogic', () => {
    let logic: ReturnType<typeof logsViewerModalLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = logsViewerModalLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('isOpen', () => {
        it('defaults to false', () => {
            expect(logic.values.isOpen).toBe(false)
        })

        it('becomes true after openLogsViewerModal', async () => {
            await expectLogic(logic, () => {
                logic.actions.openLogsViewerModal()
            }).toMatchValues({ isOpen: true })
        })

        it('becomes false after closeLogsViewerModal', async () => {
            logic.actions.openLogsViewerModal()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.closeLogsViewerModal()
            }).toMatchValues({ isOpen: false })
        })
    })

    describe('viewerId', () => {
        it('defaults to modal', () => {
            expect(logic.values.viewerId).toBe('modal')
        })

        it.each(['custom-id', 'my-viewer', 'tab-1'])('uses provided id %s', async (id) => {
            await expectLogic(logic, () => {
                logic.actions.openLogsViewerModal({ id })
            }).toMatchValues({ viewerId: id })
        })

        it('falls back to modal when no options provided', async () => {
            await expectLogic(logic, () => {
                logic.actions.openLogsViewerModal()
            }).toMatchValues({ viewerId: 'modal' })
        })

        it('falls back to modal when id is not provided in options', async () => {
            await expectLogic(logic, () => {
                logic.actions.openLogsViewerModal({ fullScreen: false })
            }).toMatchValues({ viewerId: 'modal' })
        })
    })

    describe('fullScreen', () => {
        it('defaults to true', () => {
            expect(logic.values.fullScreen).toBe(true)
        })

        it.each([true, false])('uses provided fullScreen value %s', async (fullScreen) => {
            await expectLogic(logic, () => {
                logic.actions.openLogsViewerModal({ fullScreen })
            }).toMatchValues({ fullScreen })
        })

        it('falls back to true when no options provided', async () => {
            await expectLogic(logic, () => {
                logic.actions.openLogsViewerModal()
            }).toMatchValues({ fullScreen: true })
        })

        it('falls back to true when fullScreen is not provided in options', async () => {
            await expectLogic(logic, () => {
                logic.actions.openLogsViewerModal({ id: 'some-id' })
            }).toMatchValues({ fullScreen: true })
        })
    })

    describe('initialFilters', () => {
        it('defaults to null', () => {
            expect(logic.values.initialFilters).toBeNull()
        })

        it('stores provided initialFilters', async () => {
            const filters = { searchTerm: 'session_id:abc' }
            await expectLogic(logic, () => {
                logic.actions.openLogsViewerModal({ initialFilters: filters })
            }).toMatchValues({ initialFilters: filters })
        })

        it('defaults to null when not provided in options', async () => {
            await expectLogic(logic, () => {
                logic.actions.openLogsViewerModal({ id: 'some-id' })
            }).toMatchValues({ initialFilters: null })
        })

        it('keeps initialFilters on close, while the modal renders out its exit animation', async () => {
            const filters = { searchTerm: 'test' }
            logic.actions.openLogsViewerModal({ initialFilters: filters })
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.closeLogsViewerModal()
            }).toMatchValues({ initialFilters: filters })
        })
    })

    describe('viewer scope', () => {
        const pinnedFilters: UniversalFiltersGroup = {
            type: FilterLogicalOperator.And,
            values: [
                {
                    key: 'trace_id',
                    type: PropertyFilterType.Log,
                    operator: PropertyOperator.Exact,
                    value: ['abc'],
                },
            ],
        }

        it('keeps the scope the opening viewer was embedded with', async () => {
            await expectLogic(logic, () => {
                logic.actions.openLogsViewerModal({ id: 'person-1', pinnedFilters, personId: 'a-person-uuid' })
            }).toMatchValues({ pinnedFilters, personId: 'a-person-uuid' })
        })

        it('holds the scope through close, so the closing viewer never queries unscoped', async () => {
            logic.actions.openLogsViewerModal({ id: 'person-1', pinnedFilters, personId: 'a-person-uuid' })
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.closeLogsViewerModal()
            }).toMatchValues({ pinnedFilters, personId: 'a-person-uuid' })
        })

        it('drops the scope when reopened from an unscoped entry point', async () => {
            logic.actions.openLogsViewerModal({ id: 'person-1', pinnedFilters, personId: 'a-person-uuid' })
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.closeLogsViewerModal()

            await expectLogic(logic, () => {
                logic.actions.openLogsViewerModal({ id: 'modal' })
            }).toMatchValues({ pinnedFilters: null, personId: null })
        })
    })

    describe('closes on navigation', () => {
        it.each([
            { description: 'when open', openFirst: true },
            { description: 'when already closed', openFirst: false },
        ])('modal is closed after scene navigation ($description)', async ({ openFirst }) => {
            if (openFirst) {
                logic.actions.openLogsViewerModal()
                await expectLogic(logic).toFinishAllListeners()
            }

            await expectLogic(logic, () => {
                router.actions.push('/project/1/dashboard')
            }).toMatchValues({ isOpen: false })
        })

        it('does not react to query/hash-only changes on the same pathname', async () => {
            router.actions.push('/project/1/logs')
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.openLogsViewerModal()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                router.actions.push('/project/1/logs', { search: 'foo' })
            }).toMatchValues({ isOpen: true })
        })
    })

    describe('open/close cycle', () => {
        it('restores all state on reopen with different options', async () => {
            logic.actions.openLogsViewerModal({ id: 'first', fullScreen: false })
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.closeLogsViewerModal()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.openLogsViewerModal({ id: 'second', fullScreen: true })
            }).toMatchValues({ isOpen: true, viewerId: 'second', fullScreen: true })
        })

        it('dispatches open and close actions in sequence', async () => {
            await expectLogic(logic, () => {
                logic.actions.openLogsViewerModal()
            }).toDispatchActions(['openLogsViewerModal'])

            await expectLogic(logic, () => {
                logic.actions.closeLogsViewerModal()
            }).toDispatchActions(['closeLogsViewerModal'])
        })
    })
})
