import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext, PropertyOperator } from '~/types'

import { metricsOverviewRetrieve, metricsValuesRetrieve } from '../generated/api'
import type { _MetricsOverviewResponseApi } from '../generated/api.schemas'
import { metricsSceneLogic } from '../metricsSceneLogic'
import { metricsOverviewLogic } from './metricsOverviewLogic'
import { metricsViewerLogic } from './metricsViewerLogic'

jest.mock('../generated/api', () => ({
    metricsAttributeValuesRetrieve: jest.fn(),
    metricsAttributesRetrieve: jest.fn(),
    metricsCharacterizeCreate: jest.fn(),
    metricsExplainCreate: jest.fn(),
    metricsHasMetricsRetrieve: jest.fn(),
    metricsOverviewRetrieve: jest.fn(),
    metricsQueryCreate: jest.fn(),
    metricsSamplesCreate: jest.fn(),
    metricsValuesRetrieve: jest.fn(),
}))

const OVERVIEW_FIXTURE: _MetricsOverviewResponseApi = {
    last_seen: '2026-08-21T10:00:00+00:00',
    metric_names: 3,
    series: 4,
    lookback_seconds: 86400,
    services: [
        { service_name: 'api', metric_names: 2, series: 3, last_seen: '2026-08-21T10:00:00+00:00' },
        { service_name: 'worker', metric_names: 1, series: 1, last_seen: '2026-08-21T09:00:00+00:00' },
    ],
}

describe('metricsOverviewLogic', () => {
    let logic: ReturnType<typeof metricsOverviewLogic.build>

    beforeEach(() => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                [AccessControlResourceType.Metrics]: AccessControlLevel.Viewer,
            },
        } as AppContext
        initKeaTests()
        jest.mocked(metricsOverviewRetrieve).mockReset()
        jest.mocked(metricsOverviewRetrieve).mockResolvedValue(OVERVIEW_FIXTURE as any)
        // The name picker mounts alongside the viewer logic and loads on mount.
        jest.mocked(metricsValuesRetrieve).mockResolvedValue({ results: [] } as any)
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads the overview on mount', async () => {
        logic = metricsOverviewLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadOverviewSuccess']).toMatchValues({
            overview: OVERVIEW_FIXTURE,
        })
    })

    // The row click is the overview -> viewer handoff: a wrong filter shape or
    // operator silently lands the user on an unfiltered viewer.
    it('viewService narrows the viewer to the service and switches tab', async () => {
        logic = metricsOverviewLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.viewService('api')
        }).toDispatchActions([
            metricsViewerLogic.actionTypes.setFilterGroup,
            metricsSceneLogic.actionTypes.setActiveTab,
        ])

        expect(metricsSceneLogic.values.activeTab).toBe('viewer')
        const chip = metricsViewerLogic.values.filterGroup.values[0]
        expect((chip as any).values[0]).toMatchObject({
            key: 'service_name',
            value: ['api'],
            operator: PropertyOperator.Exact,
        })
    })
})
