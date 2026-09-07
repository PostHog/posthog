import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { metricsOverviewRetrieve, metricsValuesRetrieve } from '../generated/api'
import type { _MetricsOverviewResponseApi } from '../generated/api.schemas'
import { metricsSceneLogic } from '../metricsSceneLogic'
import { metricNamePickerLogic } from './metricNamePickerLogic'
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

    // The row click is the overview -> viewer handoff. Asserting the chip alone is not
    // enough: the viewer drops filter values it cannot send, so a chip can render while
    // the query goes out unfiltered. These assert `queryFilters` — what actually reaches
    // the API — including the "unknown" row, whose service_name is empty.
    it.each([
        ['a named service', 'api', { key: 'service_name', op: 'eq', value: 'api' }, ['api']],
        ['the unknown service', '', { key: 'service_name', op: 'regex', value: '^$' }, ['']],
    ])(
        'viewService sends a service filter for %s, scopes the picker, and switches tab',
        async (_name, serviceName, expected, pickerServices) => {
            logic = metricsOverviewLogic()
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.viewService(serviceName as string)
            }).toDispatchActions([
                metricsViewerLogic.actionTypes.setFilterGroup,
                metricsSceneLogic.actionTypes.setActiveTab,
            ])

            expect(metricsSceneLogic.values.activeTab).toBe('viewer')
            expect(metricsViewerLogic.values.queryFilters).toEqual([expected])
            // The landing promise: the viewer the user arrives at offers only the
            // metrics that service reports, not every metric in the project.
            expect(metricNamePickerLogic.values.services).toEqual(pickerServices)
        }
    )
})
