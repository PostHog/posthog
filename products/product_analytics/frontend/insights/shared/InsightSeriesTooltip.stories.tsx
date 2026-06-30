import { Meta, StoryObj } from '@storybook/react'

import { TimeSeriesLineChart } from '@posthog/quill-charts'
import type { TooltipContext } from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'

import type { TrendsSeriesMeta } from '../trends/shared/trendsSeriesMeta'
import { InsightSeriesTooltip } from './InsightSeriesTooltip'

const meta: Meta = {
    title: 'Insights/InsightSeriesTooltip',
    parameters: {
        layout: 'centered',
        mockDate: '2024-06-12',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<{}>

const LABELS = ['2024-06-10', '2024-06-11', '2024-06-12', '2024-06-13', '2024-06-14']
const ACTION = { id: '$pageview', name: '$pageview', type: 'events' as const, order: 0 }

function Chart({
    series,
    tooltipProps,
}: {
    series: Parameters<typeof TimeSeriesLineChart<TrendsSeriesMeta>>[0]['series']
    tooltipProps: Omit<React.ComponentProps<typeof InsightSeriesTooltip>, 'context'>
}): JSX.Element {
    const theme = buildTheme()
    return (
        <div style={{ width: 600, height: 300 }}>
            <TimeSeriesLineChart<TrendsSeriesMeta>
                series={series}
                labels={LABELS}
                theme={theme}
                config={{ showGrid: true, showCrosshair: true, tooltip: { pinnable: true, placement: 'cursor' } }}
                tooltip={(ctx: TooltipContext<TrendsSeriesMeta>) => (
                    <InsightSeriesTooltip<TrendsSeriesMeta> context={ctx} {...tooltipProps} />
                )}
            />
        </div>
    )
}

/** Two plain events, no breakdown. */
export const Basic: Story = {
    render: () => (
        <Chart
            series={[
                {
                    key: 'pageview',
                    label: '$pageview',
                    color: '#7c3aed',
                    data: [1200, 980, 1450, 1100, 1600],
                    meta: { action: ACTION, days: LABELS, order: 0 },
                },
                {
                    key: 'signup',
                    label: 'user signed up',
                    color: '#059669',
                    data: [340, 280, 420, 310, 480],
                    meta: {
                        action: { id: 'user signed up', name: 'user signed up', type: 'events' as const, order: 1 },
                        days: LABELS,
                        order: 1,
                    },
                },
            ]}
            tooltipProps={{ timezone: 'UTC', interval: 'day' }}
        />
    ),
}

/** URL breakdown — long values clip; shorter ones don't waste space. */
export const BreakdownByUrl: Story = {
    render: () => (
        <Chart
            series={[
                {
                    key: 'home',
                    label: 'https://hedgebox.net',
                    color: '#7c3aed',
                    data: [5343, 4200, 6100, 4800, 5900],
                    meta: { action: ACTION, breakdown_value: 'https://hedgebox.net', days: LABELS, order: 0 },
                },
                {
                    key: 'pricing',
                    label: 'https://hedgebox.net/pricing?utm_source=google',
                    color: '#059669',
                    data: [1771, 1500, 2100, 1400, 1900],
                    meta: {
                        action: ACTION,
                        breakdown_value: 'https://hedgebox.net/pricing?utm_source=google',
                        days: LABELS,
                        order: 1,
                    },
                },
                {
                    key: 'files',
                    label: 'https://hedgebox.net/files/019-very-long-path-that-truncates',
                    color: '#db2777',
                    data: [1604, 1200, 1800, 1300, 1700],
                    meta: {
                        action: ACTION,
                        breakdown_value: 'https://hedgebox.net/files/019-very-long-path-that-truncates',
                        days: LABELS,
                        order: 2,
                    },
                },
            ]}
            tooltipProps={{ timezone: 'UTC', interval: 'day' }}
        />
    ),
}

/** Compare mode — Current/Previous label stays visible even with a long URL. */
export const ComparePeriod: Story = {
    render: () => (
        <Chart
            series={[
                {
                    key: 'current-home',
                    label: 'https://hedgebox.net (current)',
                    color: '#7c3aed',
                    data: [5343, 4200, 6100, 4800, 5900],
                    meta: {
                        action: ACTION,
                        breakdown_value: 'https://hedgebox.net',
                        compare_label: 'current' as const,
                        days: LABELS,
                        order: 0,
                    },
                },
                {
                    key: 'prev-home',
                    label: 'https://hedgebox.net (previous)',
                    color: 'rgba(124,58,237,0.4)',
                    data: [4901, 3800, 5600, 4100, 5200],
                    meta: {
                        action: ACTION,
                        breakdown_value: 'https://hedgebox.net',
                        compare_label: 'previous' as const,
                        days: LABELS,
                        order: 1,
                    },
                },
                {
                    key: 'current-pricing',
                    label: 'https://hedgebox.net/pricing?utm_source=google (current)',
                    color: '#059669',
                    data: [1771, 1500, 2100, 1400, 1900],
                    meta: {
                        action: ACTION,
                        breakdown_value: 'https://hedgebox.net/pricing?utm_source=google',
                        compare_label: 'current' as const,
                        days: LABELS,
                        order: 2,
                    },
                },
                {
                    key: 'prev-pricing',
                    label: 'https://hedgebox.net/pricing?utm_source=google (previous)',
                    color: 'rgba(5,150,105,0.4)',
                    data: [1590, 1300, 1900, 1200, 1700],
                    meta: {
                        action: ACTION,
                        breakdown_value: 'https://hedgebox.net/pricing?utm_source=google',
                        compare_label: 'previous' as const,
                        days: LABELS,
                        order: 3,
                    },
                },
            ]}
            tooltipProps={{ timezone: 'UTC', interval: 'day' }}
        />
    ),
}

/** Percent stack — values shown as percentages (0..1 fractions from the chart). */
export const PercentStack: Story = {
    render: () => (
        <Chart
            series={[
                {
                    key: 'chrome',
                    label: 'Chrome',
                    color: '#7c3aed',
                    data: [0.55, 0.52, 0.58, 0.54, 0.57],
                    meta: { action: ACTION, breakdown_value: 'Chrome', days: LABELS, order: 0 },
                },
                {
                    key: 'safari',
                    label: 'Safari',
                    color: '#059669',
                    data: [0.28, 0.3, 0.25, 0.29, 0.26],
                    meta: { action: ACTION, breakdown_value: 'Safari', days: LABELS, order: 1 },
                },
                {
                    key: 'firefox',
                    label: 'Firefox',
                    color: '#db2777',
                    data: [0.17, 0.18, 0.17, 0.17, 0.17],
                    meta: { action: ACTION, breakdown_value: 'Firefox', days: LABELS, order: 2 },
                },
            ]}
            tooltipProps={{ timezone: 'UTC', interval: 'day', isPercentStackView: true }}
        />
    ),
}

/** Click-to-view-people footer — shown when onRowClick is provided. */
export const WithPersonsFooter: Story = {
    render: () => (
        <Chart
            series={[
                {
                    key: 'pageview',
                    label: '$pageview',
                    color: '#7c3aed',
                    data: [1200, 980, 1450, 1100, 1600],
                    meta: { action: ACTION, days: LABELS, order: 0 },
                },
            ]}
            tooltipProps={{ timezone: 'UTC', interval: 'day', onRowClick: () => {} }}
        />
    ),
}
