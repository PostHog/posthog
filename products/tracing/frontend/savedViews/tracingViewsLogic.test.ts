import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { tracingFiltersLogic } from '../tracingFiltersLogic'
import { tracingViewsListLogic } from './tracingViewsListLogic'
import { TracingView, tracingViewsLogic } from './tracingViewsLogic'

const mockView = (overrides: Partial<TracingView> = {}): TracingView => ({
    id: 'view-1',
    short_id: 'abc123',
    name: 'My view',
    filters: {},
    pinned: false,
    created_at: '2026-06-01T00:00:00Z',
    created_by: null,
    updated_at: null,
    ...overrides,
})

describe('tracing saved views', () => {
    let filtersLogic: ReturnType<typeof tracingFiltersLogic.build>
    let viewsLogic: ReturnType<typeof tracingViewsLogic.build>
    let listLogic: ReturnType<typeof tracingViewsListLogic.build>

    beforeEach(() => {
        initKeaTests()
        // openModal triggers loadViews → api.get; keep it from hitting the network.
        jest.spyOn(api, 'get').mockResolvedValue({ results: [] })
        filtersLogic = tracingFiltersLogic()
        filtersLogic.mount()
        viewsLogic = tracingViewsLogic()
        viewsLogic.mount()
        listLogic = tracingViewsListLogic()
        listLogic.mount()
    })

    afterEach(() => {
        listLogic?.unmount()
        viewsLogic?.unmount()
        filtersLogic?.unmount()
        jest.restoreAllMocks()
    })

    describe('saveView', () => {
        it('persists only the saveable filter subset, excluding ephemeral compare state', async () => {
            const createSpy = jest.spyOn(api, 'create').mockResolvedValue(mockView())

            filtersLogic.actions.setServiceNames(['api'])
            filtersLogic.actions.setViewMode('spans')
            filtersLogic.actions.setSort('duration', 'ASC')
            // Ephemeral state that must NOT be saved.
            filtersLogic.actions.setCompareMode(true)

            listLogic.actions.setViewName('Slow spans')
            await expectLogic(listLogic, () => {
                listLogic.actions.saveView()
            }).toFinishAllListeners()

            expect(createSpy).toHaveBeenCalledTimes(1)
            const payload = createSpy.mock.calls[0][1] as { name: string; filters: Record<string, any> }
            expect(payload.name).toBe('Slow spans')
            expect(payload.filters).toEqual({
                dateRange: { date_from: '-1h', date_to: null },
                serviceNames: ['api'],
                filterGroup: filtersLogic.values.filterGroup,
                orderBy: 'duration',
                orderDirection: 'ASC',
                viewMode: 'spans',
            })
            expect(payload.filters).not.toHaveProperty('compareMode')
            expect(payload.filters).not.toHaveProperty('currentWindowOverride')
            expect(payload.filters).not.toHaveProperty('previousWindowOverride')
        })

        it('does nothing when the name is blank', async () => {
            const createSpy = jest.spyOn(api, 'create').mockResolvedValue(mockView())

            listLogic.actions.setViewName('   ')
            await expectLogic(listLogic, () => {
                listLogic.actions.saveView()
            }).toFinishAllListeners()

            expect(createSpy).not.toHaveBeenCalled()
        })
    })

    describe('loadView', () => {
        it('restores the saved filters into tracingFiltersLogic', async () => {
            const view = mockView({
                filters: { serviceNames: ['web'], viewMode: 'spans', orderBy: 'duration', orderDirection: 'DESC' },
            })

            await expectLogic(viewsLogic, () => {
                viewsLogic.actions.loadView(view)
            }).toFinishAllListeners()

            expect(filtersLogic.values.serviceNames).toEqual(['web'])
            expect(filtersLogic.values.viewMode).toBe('spans')
            expect(filtersLogic.values.orderBy).toBe('duration')
            expect(filtersLogic.values.orderDirection).toBe('DESC')
        })

        it('closes the list modal when a view is loaded', async () => {
            listLogic.actions.openModal()
            expect(listLogic.values.isModalOpen).toBe(true)

            viewsLogic.actions.loadView(mockView())
            expect(listLogic.values.isModalOpen).toBe(false)
        })
    })

    describe('deleteView', () => {
        it('optimistically removes the view from the list', async () => {
            jest.spyOn(api, 'delete').mockResolvedValue(undefined)
            // Seed the loader state with two views.
            jest.spyOn(api, 'get').mockResolvedValue({
                results: [mockView({ short_id: 'keep' }), mockView({ short_id: 'drop' })],
            })
            await expectLogic(viewsLogic, () => {
                viewsLogic.actions.loadViews()
            }).toFinishAllListeners()
            expect(viewsLogic.values.views).toHaveLength(2)

            viewsLogic.actions.deleteView('drop')
            expect(viewsLogic.values.views.map((v) => v.short_id)).toEqual(['keep'])
        })
    })
})
