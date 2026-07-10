import { initKeaTests } from '~/test/init'

import { metricsViewsCreate, metricsViewsList } from 'products/metrics/frontend/generated/api'
import type { MetricsViewApi } from 'products/metrics/frontend/generated/api.schemas'

import { metricsViewerLogic } from '../metricsViewerLogic'
import { metricsViewsLogic } from './metricsViewsLogic'

jest.mock('products/metrics/frontend/generated/api', () => ({
    metricsViewsList: jest.fn(async () => ({ count: 0, results: [] })),
    metricsViewsCreate: jest.fn(async (_: string, body: Record<string, unknown>) => ({
        ...body,
        id: '1',
        short_id: 'abc123',
        created_at: '2026-01-01T00:00:00Z',
        created_by: null,
        updated_at: null,
    })),
    metricsViewsDestroy: jest.fn(async () => undefined),
    metricsQueryCreate: jest.fn(async () => ({ results: [] })),
    metricsCharacterizeCreate: jest.fn(async () => null),
    metricsValuesRetrieve: jest.fn(async () => ({ results: [] })),
    metricsAttributesRetrieve: jest.fn(async () => ({ results: [], count: 0 })),
}))

const VIEW: MetricsViewApi = {
    id: '1',
    short_id: 'abc123',
    name: 'Error rate',
    filters: { metricName: 'queue_depth', aggregation: 'rate' },
    pinned: false,
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    updated_at: null,
}

describe('metricsViewsLogic', () => {
    let logic: ReturnType<typeof metricsViewsLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        logic = metricsViewsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loading a view replays its filters into the viewer', () => {
        logic.actions.loadView(VIEW)
        expect(metricsViewerLogic.values.metricName).toBe('queue_depth')
        expect(metricsViewerLogic.values.aggregation).toBe('rate')
    })

    it('creates a view with the given name and filters', async () => {
        await logic.asyncActions.createView({ name: 'My view', filters: { metricName: 'queue_depth' } })
        expect(metricsViewsCreate as jest.Mock).toHaveBeenCalledWith(expect.any(String), {
            name: 'My view',
            filters: { metricName: 'queue_depth' },
        })
        expect(logic.values.views.map((v) => v.name)).toEqual(['My view'])
    })

    it('loads views from the API when requested', async () => {
        ;(metricsViewsList as jest.Mock).mockResolvedValueOnce({ count: 1, results: [VIEW] })
        await logic.asyncActions.loadViews()
        expect(logic.values.views).toEqual([VIEW])
    })
})
