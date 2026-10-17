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
})
