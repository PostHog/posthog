import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { insightsApi } from 'scenes/insights/utils/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import {
    AccessControlLevel,
    AccessControlResourceType,
    AppContext,
    InsightShortId,
    QueryBasedInsightModel,
} from '~/types'

import {
    metricsAttributesRetrieve,
    metricsQueryCreate,
    metricsValuesRetrieve,
} from 'products/metrics/frontend/generated/api'

import { MetricsViewer } from './MetricsViewer'
import { metricsViewerLogic } from './metricsViewerLogic'

jest.mock('products/metrics/frontend/generated/api', () => ({
    ...jest.requireActual('products/metrics/frontend/generated/api'),
    metricsValuesRetrieve: jest.fn(),
    metricsQueryCreate: jest.fn(),
    metricsSamplesCreate: jest.fn(),
    metricsAttributesRetrieve: jest.fn(),
    metricsCharacterizeCreate: jest.fn(),
}))
jest.mock('scenes/insights/utils/api', () => ({
    insightsApi: { create: jest.fn(), update: jest.fn() },
}))

// What the viewer reads off a freshly saved insight: `short_id` keys the insight logic the
// picker binds to, and `id` is what a dashboard write would patch. Typed as a Partial — the
// shape `insightsApi.create` accepts — so these two fields are checked without padding the
// fixture with the rest of the model, which this flow never touches.
const SAVED_INSIGHT: Partial<QueryBasedInsightModel> = { id: 7, short_id: 'insight7' as InsightShortId }

describe('MetricsViewer', () => {
    let logic: ReturnType<typeof metricsViewerLogic.build>

    beforeEach(() => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                [AccessControlResourceType.Metrics]: AccessControlLevel.Viewer,
                [AccessControlResourceType.Insight]: AccessControlLevel.Editor,
            },
        } as AppContext
        useMocks({ get: { '/api/environments/:team_id/dashboards/': { count: 0, results: [] } } })
        initKeaTests()
        jest.mocked(metricsValuesRetrieve).mockResolvedValue({ results: [] })
        jest.mocked(metricsQueryCreate).mockResolvedValue({ results: [] })
        jest.mocked(metricsAttributesRetrieve).mockResolvedValue({ results: [], count: 0 })
        jest.mocked(insightsApi.create).mockResolvedValue(SAVED_INSIGHT as QueryBasedInsightModel)
        logic = metricsViewerLogic()
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic?.unmount()
    })

    // "Add to dashboard" saves the query as an insight, then hands off to the shared dashboard
    // picker. That picker's "Add to a new dashboard" does nothing unless the create-dashboard
    // dialog is rendered alongside it, which is easy to leave out of a scene.
    it('opens the create-dashboard dialog from the dashboard picker', async () => {
        logic.actions.setMetricName('http.server.duration')

        render(
            <Provider>
                <MetricsViewer />
            </Provider>
        )

        fireEvent.click(screen.getByText('Add to dashboard'))

        fireEvent.click(await screen.findByText('Add to a new dashboard'))

        expect(await screen.findByText('Create a dashboard')).toBeInTheDocument()
    })
})
