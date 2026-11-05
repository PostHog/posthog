import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { metricsAttributesRetrieve, metricsAttributeValuesRetrieve } from '../../generated/api'
import { metricsViewerLogic } from '../metricsViewerLogic'
import { DEFAULT_EXPANDED_FACETS, metricsFacetRailLogic } from './metricsFacetRailLogic'
import { metricsFacetValuesLogic } from './metricsFacetValuesLogic'

jest.mock('../../generated/api', () => ({
    ...jest.requireActual('../../generated/api'),
    metricsAttributesRetrieve: jest.fn(),
    metricsAttributeValuesRetrieve: jest.fn(),
}))

const KEYS = Array.from({ length: DEFAULT_EXPANDED_FACETS + 2 }, (_, i) => ({ name: `key_${i}`, value_count: 10 - i }))

describe('metricsFacetRailLogic', () => {
    let viewer: ReturnType<typeof metricsViewerLogic.build>
    let logic: ReturnType<typeof metricsFacetRailLogic.build>

    beforeEach(() => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                [AccessControlResourceType.Metrics]: AccessControlLevel.Viewer,
            },
        } as AppContext
        // The collapse state persists, so one test's toggles would leak into the next.
        localStorage.clear()
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.METRICS]: true })
        jest.mocked(metricsAttributesRetrieve).mockReset().mockResolvedValue({ results: KEYS, count: KEYS.length })
        jest.mocked(metricsAttributeValuesRetrieve)
            .mockReset()
            .mockResolvedValue({ results: [{ id: 'prod', name: 'prod', count: 3 }] })
        viewer = metricsViewerLogic()
        viewer.mount()
        logic = metricsFacetRailLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        viewer.unmount()
    })

    it('lists the active metric attribute keys as facets after the service facet', async () => {
        viewer.actions.setMetricName('http_requests')

        await expectLogic(logic).toDispatchActions(['loadAttributeKeysSuccess'])

        expect(jest.mocked(metricsAttributesRetrieve).mock.lastCall?.[1]).toMatchObject({
            metricName: 'http_requests',
        })
        expect(logic.values.visibleFacets.map((facet) => facet.attributeKey)).toEqual([
            'service_name',
            ...KEYS.map((key) => key.name),
        ])
    })

    it('starts facets past the first few collapsed, and remembers a toggle', async () => {
        await expectLogic(logic).toDispatchActions(['loadAttributeKeysSuccess'])
        const facets = logic.values.visibleFacets
        const firstCollapsed = facets[DEFAULT_EXPANDED_FACETS]

        expect(logic.values.collapsedFacetKeys).toEqual(facets.slice(DEFAULT_EXPANDED_FACETS).map((f) => f.key))

        logic.actions.toggleFacetCollapsed(firstCollapsed.key)
        expect(logic.values.collapsedFacetKeys).not.toContain(firstCollapsed.key)

        logic.actions.toggleFacetCollapsed(facets[0].key)
        expect(logic.values.collapsedFacetKeys).toContain(facets[0].key)
    })

    it('writes a toggled value into the active clause filters', () => {
        logic.actions.toggleFacetValue('env', 'prod')

        expect(viewer.values.activeClause.filterGroup).toEqual({
            type: 'AND',
            values: [
                {
                    type: 'AND',
                    values: [{ key: 'env', type: 'metric_attribute', operator: 'exact', value: ['prod'] }],
                },
            ],
        })
    })

    it('loads facet values for the active metric only while the facet is expanded', async () => {
        viewer.actions.setMetricName('http_requests')
        await expectLogic(logic).toDispatchActions(['loadAttributeKeysSuccess'])
        const collapsed = logic.values.visibleFacets[DEFAULT_EXPANDED_FACETS]
        const values = metricsFacetValuesLogic({ facet: collapsed })
        values.mount()

        await expectLogic(values).toNotHaveDispatchedActions(['loadFacetValues'])

        logic.actions.toggleFacetCollapsed(collapsed.key)
        await expectLogic(values).toDispatchActions(['loadFacetValuesSuccess'])

        expect(jest.mocked(metricsAttributeValuesRetrieve).mock.lastCall?.[1]).toMatchObject({
            key: collapsed.attributeKey,
            metricName: 'http_requests',
        })
        expect(values.values.facetValues).toEqual([{ value: 'prod', label: 'prod', count: 3 }])
        values.unmount()
    })

    it('skips the values request when the facet collapses during the debounce', async () => {
        viewer.actions.setMetricName('http_requests')
        await expectLogic(logic).toDispatchActions(['loadAttributeKeysSuccess'])
        const [expanded] = logic.values.visibleFacets
        const values = metricsFacetValuesLogic({ facet: expanded })
        values.mount()

        logic.actions.toggleFacetCollapsed(expanded.key)
        await expectLogic(values).toDispatchActions(['loadFacetValuesSuccess'])

        expect(metricsAttributeValuesRetrieve).not.toHaveBeenCalled()
        values.unmount()
    })

    it('shows only the service facet until the keys for a new metric arrive', async () => {
        viewer.actions.setMetricName('http_requests')
        await expectLogic(logic).toDispatchActions(['loadAttributeKeysSuccess'])
        let releaseKeys: (response: {
            results: { name: string; value_count: number }[]
            count: number
        }) => void = () => {}
        jest.mocked(metricsAttributesRetrieve).mockReturnValueOnce(
            new Promise((resolve) => {
                releaseKeys = resolve
            })
        )

        viewer.actions.setMetricName('queue_depth')
        expect(logic.values.visibleFacets.map((facet) => facet.attributeKey)).toEqual(['service_name'])

        releaseKeys({ results: [{ name: 'queue', value_count: 1 }], count: 1 })
        await expectLogic(logic).toDispatchActions(['loadAttributeKeysSuccess'])
        expect(logic.values.visibleFacets.map((facet) => facet.attributeKey)).toEqual(['service_name', 'queue'])
    })

    it('reports a failed attribute-key load and retries it', async () => {
        jest.mocked(metricsAttributesRetrieve).mockRejectedValueOnce(new Error('timeout'))
        viewer.actions.setMetricName('http_requests')

        await expectLogic(logic).toDispatchActions(['loadAttributeKeysFailure']).toMatchValues({
            attributeKeysFailed: true,
        })
        expect(logic.values.visibleFacets.map((facet) => facet.attributeKey)).toEqual(['service_name'])

        logic.actions.retryAttributeKeys()
        await expectLogic(logic).toDispatchActions(['loadAttributeKeysSuccess']).toMatchValues({
            attributeKeysFailed: false,
        })
        expect(logic.values.visibleFacets).toHaveLength(KEYS.length + 1)
    })

    it('reloads the keys and the expanded facet values on each auto-refresh tick, but not mid-load', async () => {
        viewer.actions.setMetricName('http_requests')
        await expectLogic(logic).toDispatchActions(['loadAttributeKeysSuccess'])
        const expanded = logic.values.visibleFacets[0]
        const collapsed = logic.values.visibleFacets[DEFAULT_EXPANDED_FACETS]
        const expandedValues = metricsFacetValuesLogic({ facet: expanded })
        const collapsedValues = metricsFacetValuesLogic({ facet: collapsed })
        expandedValues.mount()
        collapsedValues.mount()
        await expectLogic(expandedValues).toDispatchActions(['loadFacetValuesSuccess'])
        jest.mocked(metricsAttributesRetrieve).mockClear()
        jest.mocked(metricsAttributeValuesRetrieve).mockClear()

        viewer.actions.liveRefreshTick()
        // The facets stay on screen while the refresh runs.
        expect(logic.values.visibleFacets).toHaveLength(KEYS.length + 1)
        await expectLogic(logic).toDispatchActions(['loadAttributeKeysSuccess'])
        await expectLogic(expandedValues).toDispatchActions(['loadFacetValuesSuccess'])

        expect(metricsAttributesRetrieve).toHaveBeenCalledTimes(1)
        expect(jest.mocked(metricsAttributeValuesRetrieve).mock.calls.map((call) => call[1].key)).toEqual([
            expanded.attributeKey,
        ])

        // A query slower than the refresh interval: the next tick must not restart it.
        jest.mocked(metricsAttributesRetrieve).mockClear()
        jest.mocked(metricsAttributeValuesRetrieve).mockClear()
        let releaseKeys: () => void = () => {}
        let releaseValues: () => void = () => {}
        let keysRequested: () => void = () => {}
        let valuesRequested: () => void = () => {}
        const bothRequested = Promise.all([
            new Promise<void>((resolve) => {
                keysRequested = resolve
            }),
            new Promise<void>((resolve) => {
                valuesRequested = resolve
            }),
        ])
        jest.mocked(metricsAttributesRetrieve).mockImplementationOnce(() => {
            keysRequested()
            return new Promise((resolve) => {
                releaseKeys = () => resolve({ results: KEYS, count: KEYS.length })
            })
        })
        jest.mocked(metricsAttributeValuesRetrieve).mockImplementationOnce(() => {
            valuesRequested()
            return new Promise((resolve) => {
                releaseValues = () => resolve({ results: [{ id: 'prod', name: 'prod', count: 3 }] })
            })
        })
        viewer.actions.liveRefreshTick()
        await bothRequested

        viewer.actions.liveRefreshTick()
        releaseKeys()
        releaseValues()
        await expectLogic(logic).toDispatchActions(['loadAttributeKeysSuccess'])
        await expectLogic(expandedValues).toDispatchActions(['loadFacetValuesSuccess'])

        expect(metricsAttributesRetrieve).toHaveBeenCalledTimes(1)
        expect(metricsAttributeValuesRetrieve).toHaveBeenCalledTimes(1)

        // Hidden rail: ticks do not poll the keys, and reopening the rail refreshes them once.
        jest.mocked(metricsAttributesRetrieve).mockClear()
        viewer.actions.setLiveRefresh(true)
        logic.actions.setRailCollapsed(true)
        viewer.actions.liveRefreshTick()
        await expectLogic(logic).toFinishAllListeners()
        expect(metricsAttributesRetrieve).not.toHaveBeenCalled()

        logic.actions.setRailCollapsed(false)
        await expectLogic(logic).toDispatchActions(['loadAttributeKeysSuccess'])
        expect(metricsAttributesRetrieve).toHaveBeenCalledTimes(1)
        viewer.actions.setLiveRefresh(false)
        expandedValues.unmount()
        collapsedValues.unmount()
    })
})
