import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import {
    metricsSuggestedDashboardsDashboardCreate,
    metricsSuggestedDashboardsList,
} from 'products/metrics/frontend/generated/api'
import type { MetricsSuggestedDashboardApi } from 'products/metrics/frontend/generated/api.schemas'

import { suggestedDashboardsLogic } from './suggestedDashboardsLogic'

jest.mock('products/metrics/frontend/generated/api', () => ({
    ...jest.requireActual('products/metrics/frontend/generated/api'),
    metricsSuggestedDashboardsDashboardCreate: jest.fn(),
    metricsSuggestedDashboardsList: jest.fn(),
}))

const mockCreate = jest.mocked(metricsSuggestedDashboardsDashboardCreate)
const mockList = jest.mocked(metricsSuggestedDashboardsList)

const suggestion = (overrides: Partial<MetricsSuggestedDashboardApi> = {}): MetricsSuggestedDashboardApi => ({
    id: '0b5e7c3a-2f1d-4c8e-9a6b-3d2f1e0c9b8a',
    template_id: '1c6f8d4b-3a2e-4d9f-8b7c-4e3a2f1d0c9b',
    name: 'Envoy proxy',
    description: 'Upstream traffic, errors, latency and connections of Envoy clusters.',
    reason: 'Cluster traffic, errors and latency',
    panel_count: 11,
    matched_metric_count: 10,
    coverage: 1,
    dashboard_id: null,
    ...overrides,
})

describe('suggestedDashboardsLogic', () => {
    let logic: ReturnType<typeof suggestedDashboardsLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockCreate.mockReset().mockResolvedValue({ dashboard_id: 42 })
        mockList.mockReset().mockResolvedValue([suggestion()])
        logic = suggestedDashboardsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it.each([
        ['a new suggestion creates its dashboard once', null, 1, 42],
        ['a created suggestion opens its dashboard', 7, 0, 7],
    ])('%s', async (_name, dashboardId, createCalls, openedId) => {
        const item = suggestion({ dashboard_id: dashboardId })

        await expectLogic(logic, () => {
            logic.actions.openSuggestion(item)
            logic.actions.openSuggestion(item)
        }).toFinishAllListeners()

        expect(mockCreate).toHaveBeenCalledTimes(createCalls)
        expect(router.values.location.pathname).toContain(urls.dashboard(openedId))
        expect(logic.values.openingId).toBeNull()
    })
})
