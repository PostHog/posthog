import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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

import { MetricsGroupByButton } from './MetricsGroupByButton'
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

    it('shows series counts in the group-by dropdown and selects the attribute key', async () => {
        jest.mocked(metricsAttributesRetrieve).mockResolvedValue({
            results: [
                { name: 'service_name', series_count: 20 },
                { name: 'env', series_count: 2 },
            ],
            count: 2,
        })
        const onChange = jest.fn()
        render(<MetricsGroupByButton groupByKeys={[]} onChange={onChange} disabledReason={null} />)
        fireEvent.click(screen.getByRole('button', { name: 'Group by' }))
        const serviceOption = await screen.findByRole('button', { name: /service_name\s*20/ })
        const envOption = screen.getByRole('button', { name: /env\s*2/ })
        expect(serviceOption.compareDocumentPosition(envOption) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
        await userEvent.hover(screen.getByText('20'))
        expect(await screen.findByText('number of series')).toBeInTheDocument()
        fireEvent.change(screen.getByPlaceholderText('Group by attribute…'), { target: { value: 'e' } })
        expect(serviceOption.compareDocumentPosition(envOption) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
        fireEvent.click(envOption)
        expect(onChange).toHaveBeenCalledWith(['env'])
    })

    // The formula input only means something once a second series can feed it; showing it
    // is what makes the multi-series feature discoverable at all.
    it('reveals a second clause row and the formula input when a series is added', async () => {
        render(
            <Provider>
                <MetricsViewer />
            </Provider>
        )
        expect(screen.queryByPlaceholderText('Formula, e.g. (a - b) / a')).toBeNull()

        fireEvent.click(screen.getByText('Add series'))

        expect(await screen.findByPlaceholderText('Formula, e.g. (a - b) / a')).toBeInTheDocument()
        expect(logic.values.viewerClauses).toHaveLength(2)
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
