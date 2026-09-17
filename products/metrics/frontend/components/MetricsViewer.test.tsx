import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
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
    metricsNamesRetrieve,
} from 'products/metrics/frontend/generated/api'

import { metricNamePickerLogic } from './metricNamePickerLogic'
import { MetricsGroupByButton } from './MetricsGroupByButton'
import { MetricsViewer } from './MetricsViewer'
import { metricsViewerLogic } from './metricsViewerLogic'

jest.mock('products/metrics/frontend/generated/api', () => ({
    ...jest.requireActual('products/metrics/frontend/generated/api'),
    metricsNamesRetrieve: jest.fn(),
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
        useMocks({
            get: { '/api/environments/:team_id/dashboards/': { count: 0, results: [] } },
            post: {
                // The generic query endpoint the heatmap's MetricsHistogramQuery runs against.
                '/api/environments/:team_id/query/': { times: [], bounds: [], counts: [] },
            },
        })
        initKeaTests()
        // The picker list feeds each clause's latched OTel type; the heatmap option keys off it.
        jest.mocked(metricsNamesRetrieve).mockResolvedValue({
            results: [
                { name: 'queue_depth', metric_type: 'gauge' },
                { name: 'request_duration', metric_type: 'histogram' },
                { name: 'http.server.duration', metric_type: 'histogram' },
            ],
        })
        jest.mocked(metricsQueryCreate).mockResolvedValue({ results: [] })
        jest.mocked(metricsAttributesRetrieve).mockResolvedValue({ results: [], count: 0 })
        jest.mocked(insightsApi.create).mockResolvedValue(SAVED_INSIGHT as QueryBasedInsightModel)
        logic = metricsViewerLogic()
        logic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.METRICS_DASHBOARD_PANELS]: true })
        // Load the picker list so metric switches latch the OTel type (drives heatmap eligibility).
        metricNamePickerLogic.actions.loadItemsSuccess([
            { name: 'queue_depth', metric_type: 'gauge' },
            { name: 'request_duration', metric_type: 'histogram' },
            { name: 'http.server.duration', metric_type: 'histogram' },
        ] as any)
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
        fireEvent.click(screen.getByText('Group by'))
        const serviceOption = await screen.findByText('service_name')
        const envOption = screen.getByText('env')
        expect(serviceOption.compareDocumentPosition(envOption) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
        await userEvent.hover(screen.getByText('20'))
        expect(await screen.findByText('Number of series with this attribute')).toBeInTheDocument()
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

    // The heatmap option only makes sense for a distribution metric; the picker disables it
    // (with the reason as its tooltip) for gauges, counters, and multi-series/formula queries.
    it('disables the heatmap option for a non-histogram metric and enables it for a histogram', async () => {
        logic.actions.setMetricName('queue_depth') // a gauge
        render(
            <Provider>
                <MetricsViewer />
            </Provider>
        )

        const heatmapMenuItem = (): Element | null =>
            Array.from(document.querySelectorAll('[role="menuitem"]')).find((el) =>
                el.textContent?.includes('Heatmap')
            ) ?? null

        fireEvent.click(document.querySelector('[data-attr="metrics-viewer-display-type"]') as Element)
        expect(heatmapMenuItem()?.getAttribute('aria-disabled')).toBe('true')

        fireEvent.click(document.querySelector('[data-attr="metrics-viewer-display-type"]') as Element) // close
        logic.actions.setMetricName('request_duration') // a histogram
        fireEvent.click(document.querySelector('[data-attr="metrics-viewer-display-type"]') as Element)
        expect(heatmapMenuItem()?.getAttribute('aria-disabled')).not.toBe('true')
    })

    // Selecting the heatmap runs the histogram query and renders the grid, not the shared
    // time-series chart the other panels draw from.
    it('renders the histogram node when the heatmap display is selected on a histogram metric', async () => {
        logic.actions.setMetricName('request_duration')
        render(
            <Provider>
                <MetricsViewer />
            </Provider>
        )

        logic.actions.setDisplayType('heatmap')

        // The histogram endpoint returned an empty grid, so the node renders its empty state
        // rather than the time-series chart or the generic "no metric" prompt.
        expect(await screen.findByText('No data for this metric in the selected range.')).toBeInTheDocument()
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
