import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { savedViewsLogic } from 'lib/components/SavedViews/savedViewsLogic'

import { initKeaTests } from '~/test/init'

import { tracingFiltersLogic } from '../tracingFiltersLogic'
import { TRACING_SAVED_VIEWS_LOGIC_PROPS, TracingView, tracingViewsLogic } from './tracingViewsLogic'

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
    let savedViews: ReturnType<typeof savedViewsLogic.build>

    beforeEach(() => {
        initKeaTests()
        filtersLogic = tracingFiltersLogic()
        filtersLogic.mount()
        viewsLogic = tracingViewsLogic()
        viewsLogic.mount()
        savedViews = savedViewsLogic(TRACING_SAVED_VIEWS_LOGIC_PROPS)
        savedViews.mount()
    })

    afterEach(() => {
        savedViews?.unmount()
        viewsLogic?.unmount()
        filtersLogic?.unmount()
        jest.restoreAllMocks()
    })

    it('saves only the saveable filter subset, excluding ephemeral compare state', async () => {
        const createSpy = jest.spyOn(api, 'create').mockResolvedValue(mockView())

        filtersLogic.actions.setServiceNames(['api'])
        filtersLogic.actions.setViewMode('spans')
        filtersLogic.actions.setSort('duration', 'ASC')
        // Ephemeral state that must NOT be saved.
        filtersLogic.actions.setComparison({
            mode: 'time',
            preset: 'custom',
            currentWindowOverride: null,
            previousWindowOverride: null,
        })

        savedViews.actions.setViewName('Slow spans')
        await expectLogic(savedViews, () => {
            savedViews.actions.saveView(viewsLogic.values.savePayload)
        }).toFinishAllListeners()

        expect(createSpy).toHaveBeenCalledTimes(1)
        const [url, payload] = createSpy.mock.calls[0] as [string, { name: string; filters: Record<string, any> }]
        expect(url).toMatch(/\/tracing\/views\/$/)
        expect(payload.name).toBe('Slow spans')
        expect(payload.filters).toEqual({
            dateRange: { date_from: '-1h', date_to: null },
            serviceNames: ['api'],
            filterGroup: filtersLogic.values.filterGroup,
            orderBy: 'duration',
            orderDirection: 'ASC',
            viewMode: 'spans',
        })
        expect(payload.filters).not.toHaveProperty('comparison')
    })

    it('restores the saved filters into tracingFiltersLogic when a view is loaded', async () => {
        const view = mockView({
            filters: { serviceNames: ['web'], viewMode: 'spans', orderBy: 'duration', orderDirection: 'DESC' },
        })

        await expectLogic(viewsLogic, () => {
            savedViews.actions.loadView(view)
        }).toFinishAllListeners()

        expect(filtersLogic.values.serviceNames).toEqual(['web'])
        expect(filtersLogic.values.viewMode).toBe('spans')
        expect(filtersLogic.values.orderBy).toBe('duration')
        expect(filtersLogic.values.orderDirection).toBe('DESC')
    })
})
