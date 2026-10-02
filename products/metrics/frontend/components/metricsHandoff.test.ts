import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { metricsNamesRetrieve, metricsValuesRetrieve } from '../generated/api'
import { metricsCatalogLogic } from './metricsCatalogLogic'

jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    metricsNamesRetrieve: jest.fn(),
    metricsValuesRetrieve: jest.fn(),
    metricsQueryCreate: jest.fn(),
}))

// The catalog logic is a keyed (global) logic whose state must survive a tab flip:
// a card click preloads the viewer. The scene mounts it, so unmounting the tab
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
        jest.mocked(metricsNamesRetrieve).mockResolvedValue({ results: [] } as any)
    })

    it('a loaded catalog survives the explore tab unmounting', async () => {
        const items = [{ name: 'jobs.processed', metric_type: 'sum' }]
        jest.mocked(metricsNamesRetrieve).mockResolvedValue({ results: items } as any)

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
