import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { metricsValuesRetrieve } from '../generated/api'
import { metricsCatalogLogic } from './metricsCatalogLogic'
import { metricsFundamentalsLogic } from './metricsFundamentalsLogic'

jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    metricsValuesRetrieve: jest.fn(),
    metricsQueryCreate: jest.fn(),
    metricsExplainCreate: jest.fn(),
}))

// The catalog and fundamentals logics are keyed (global) logics whose state must
// survive a tab flip: a card click preloads the viewer, and the viewer's explain
// button preloads fundamentals. The scene mounts both, so unmounting the tab
// component that also subscribes must not reset the preloaded state.
describe('metrics cross-tab handoffs', () => {
    beforeEach(() => {
        window.POSTHOG_APP_CONTEXT = {
            current_project: { id: 997 },
            resource_access_control: {
                [AccessControlResourceType.Metrics]: AccessControlLevel.Viewer,
            },
        } as unknown as AppContext
        initKeaTests()
        jest.mocked(metricsValuesRetrieve).mockResolvedValue({ results: [] } as any)
    })

    it('explainMetric state survives the viewer tab unmounting', async () => {
        // Stand-in for the scene-level mount that keeps the logic alive across tabs.
        const sceneHold = metricsFundamentalsLogic()
        sceneHold.mount()
        // Stand-in for the MetricsClauseRow subscription inside the viewer tab.
        const viewerHold = metricsFundamentalsLogic()
        viewerHold.mount()

        await expectLogic(sceneHold, () =>
            sceneHold.actions.explainMetric({ metricName: 'cache_size', aggregation: 'avg' })
        ).toFinishAllListeners()
        expect(sceneHold.values.metricName).toBe('cache_size')

        // The viewer tab unmounts while fundamentals renders. With only the tab
        // holding a subscription, kea would unmount the logic and drop the
        // prefill; the scene hold must keep it alive.
        viewerHold.unmount()

        expect(sceneHold.values.metricName).toBe('cache_size')
        expect(sceneHold.values.aggregation).toBe('avg')
        sceneHold.unmount()
    })

    it('a loaded catalog survives the explore tab unmounting', async () => {
        const items = [{ name: 'jobs.processed', metric_type: 'sum', unit: '', last_seen: null, sparkline: [1] }]
        jest.mocked(metricsValuesRetrieve).mockResolvedValue({ results: items } as any)

        const sceneHold = metricsCatalogLogic()
        sceneHold.mount()
        await expectLogic(sceneHold).toDispatchActions(['loadCatalogSuccess'])
        const tabHold = metricsCatalogLogic()
        tabHold.mount()

        tabHold.unmount()

        expect(sceneHold.values.catalogItems).toEqual(items)
        sceneHold.unmount()
    })
})
