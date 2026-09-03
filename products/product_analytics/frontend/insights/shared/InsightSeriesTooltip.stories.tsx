import type { Meta, StoryObj } from '@storybook/react'

import { TimeSeriesLineChart } from '@posthog/quill-charts'
import { Stage, playHoverAtFraction } from '@posthog/quill-charts/story-helpers'

import { useChartTheme } from 'lib/charts/hooks'

import type { BreakdownFilter } from '~/queries/schema/schema-general'
import { CompareLabelType } from '~/types'

import type { TrendsSeriesMeta } from '../trends/shared/trendsSeriesMeta'
import { InsightSeriesTooltip } from './InsightSeriesTooltip'

const DAYS = ['2024-06-10', '2024-06-11', '2024-06-12', '2024-06-13', '2024-06-14']
const PREVIOUS_DAYS = ['2024-06-03', '2024-06-04', '2024-06-05', '2024-06-06', '2024-06-07']

const BOOLEAN_BREAKDOWN_FILTER: BreakdownFilter = { breakdown: 'is_subscribed', breakdown_type: 'event' }

interface FixtureSeries {
    label: string
    data: number[]
    /** Event name — omit for formula rows, which have no `action`. */
    event?: string
    /** Formula label carried as `series_name` for rows without an event. */
    seriesName?: string
    seriesOrder: number
    breakdown_value?: string
    compareLabel?: CompareLabelType
    /** This series' own period. A previous-period series covers earlier dates than the chart's. */
    days?: string[]
}

function buildSeries(fixtures: FixtureSeries[]): {
    key: string
    label: string
    data: number[]
    meta: TrendsSeriesMeta
}[] {
    return fixtures.map((f, i) => ({
        key: String(i),
        label: f.label,
        data: f.data,
        meta: {
            action: f.event ? { id: f.event, name: f.event, type: 'events', order: f.seriesOrder } : undefined,
            series_name: f.seriesName,
            breakdown_value: f.breakdown_value,
            compare_label: f.compareLabel,
            days: f.days ?? DAYS,
            order: f.seriesOrder,
        },
    }))
}

function TooltipChart({ fixtures }: { fixtures: FixtureSeries[] }): JSX.Element {
    const theme = useChartTheme()
    return (
        <Stage width={760}>
            <TimeSeriesLineChart<TrendsSeriesMeta>
                series={buildSeries(fixtures)}
                labels={DAYS}
                theme={theme}
                config={{ xAxis: { timezone: 'UTC', interval: 'day' } }}
                tooltip={(ctx) => (
                    <InsightSeriesTooltip
                        context={ctx}
                        breakdownFilter={BOOLEAN_BREAKDOWN_FILTER}
                        interval="day"
                        timezone="UTC"
                    />
                )}
            />
        </Stage>
    )
}

const meta: Meta<typeof InsightSeriesTooltip> = {
    title: 'Insights/InsightSeriesTooltip',
    component: InsightSeriesTooltip,
    parameters: {
        layout: 'centered',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<typeof InsightSeriesTooltip>

// Two different events with a boolean breakdown: each row is prefixed with the
// series name so the repeated true/false values stay attributable.
export const MultipleSeriesWithBreakdown: Story = {
    render: () => (
        <TooltipChart
            fixtures={[
                {
                    label: 'true',
                    data: [45, 82, 134, 210, 95],
                    event: '$pageview',
                    seriesOrder: 0,
                    breakdown_value: 'true',
                },
                {
                    label: 'false',
                    data: [20, 31, 46, 70, 38],
                    event: '$pageview',
                    seriesOrder: 0,
                    breakdown_value: 'false',
                },
                {
                    label: 'true',
                    data: [8, 12, 21, 30, 14],
                    event: 'signed_up',
                    seriesOrder: 1,
                    breakdown_value: 'true',
                },
                { label: 'false', data: [2, 4, 5, 9, 3], event: 'signed_up', seriesOrder: 1, breakdown_value: 'false' },
            ]}
        />
    ),
    play: async ({ canvasElement }) => await playHoverAtFraction(canvasElement, 0.5),
}

// The same event added twice (e.g. with different filters): names alone can't tell
// the series apart, so rows also carry the A/B letters from the insight editor.
export const SameEventSeriesWithBreakdown: Story = {
    render: () => (
        <TooltipChart
            fixtures={[
                {
                    label: 'true',
                    data: [45, 82, 134, 210, 95],
                    event: '$pageview',
                    seriesOrder: 0,
                    breakdown_value: 'true',
                },
                {
                    label: 'false',
                    data: [20, 31, 46, 70, 38],
                    event: '$pageview',
                    seriesOrder: 0,
                    breakdown_value: 'false',
                },
                {
                    label: 'true',
                    data: [8, 12, 21, 30, 14],
                    event: '$pageview',
                    seriesOrder: 1,
                    breakdown_value: 'true',
                },
                { label: 'false', data: [2, 4, 5, 9, 3], event: '$pageview', seriesOrder: 1, breakdown_value: 'false' },
            ]}
        />
    ),
    play: async ({ canvasElement }) => await playHoverAtFraction(canvasElement, 0.5),
}

// The previous row is dated; the current row's date is the header above it.
export const CompareToPreviousPeriod: Story = {
    render: () => (
        <TooltipChart
            fixtures={[
                {
                    label: '$pageview',
                    data: [45, 82, 134, 210, 95],
                    event: '$pageview',
                    seriesOrder: 0,
                    compareLabel: CompareLabelType.Current,
                },
                {
                    label: '$pageview',
                    data: [30, 64, 100, 155, 71],
                    event: '$pageview',
                    seriesOrder: 0,
                    compareLabel: CompareLabelType.Previous,
                    days: PREVIOUS_DAYS,
                },
            ]}
        />
    ),
    play: async ({ canvasElement }) => await playHoverAtFraction(canvasElement, 0.5),
}

// Compare with a breakdown: the date competes with the breakdown value for row width.
export const CompareToPreviousPeriodWithBreakdown: Story = {
    render: () => (
        <TooltipChart
            fixtures={[
                {
                    label: 'true',
                    data: [45, 82, 134, 210, 95],
                    event: '$pageview',
                    seriesOrder: 0,
                    breakdown_value: 'true',
                    compareLabel: CompareLabelType.Current,
                },
                {
                    label: 'false',
                    data: [20, 31, 46, 70, 38],
                    event: '$pageview',
                    seriesOrder: 0,
                    breakdown_value: 'false',
                    compareLabel: CompareLabelType.Current,
                },
                {
                    label: 'true',
                    data: [8, 15, 22, 34, 17],
                    event: '$pageview',
                    seriesOrder: 0,
                    breakdown_value: 'true',
                    compareLabel: CompareLabelType.Previous,
                    days: PREVIOUS_DAYS,
                },
                {
                    label: 'false',
                    data: [5, 9, 12, 19, 10],
                    event: '$pageview',
                    seriesOrder: 0,
                    breakdown_value: 'false',
                    compareLabel: CompareLabelType.Previous,
                    days: PREVIOUS_DAYS,
                },
            ]}
        />
    ),
    play: async ({ canvasElement }) => await playHoverAtFraction(canvasElement, 0.5),
}

// A long event name doesn't fit beside the breakdown value at the tooltip's max width.
// The name truncates and the breakdown value stays readable, not the other way round.
export const LongSeriesNameWithBreakdown: Story = {
    render: () => (
        <TooltipChart
            fixtures={[
                {
                    label: 'true',
                    data: [45, 82, 134, 210, 95],
                    event: 'subscription_renewal_reminder_delivered',
                    seriesOrder: 0,
                    breakdown_value: 'true',
                },
                {
                    label: 'false',
                    data: [20, 31, 46, 70, 38],
                    event: 'subscription_renewal_reminder_delivered',
                    seriesOrder: 0,
                    breakdown_value: 'false',
                },
                {
                    label: 'true',
                    data: [8, 12, 21, 30, 14],
                    event: 'subscription_renewal_reminder_delivered',
                    seriesOrder: 1,
                    breakdown_value: 'true',
                },
                {
                    label: 'false',
                    data: [2, 4, 5, 9, 3],
                    event: 'subscription_renewal_reminder_delivered',
                    seriesOrder: 1,
                    breakdown_value: 'false',
                },
            ]}
        />
    ),
    play: async ({ canvasElement }) => await playHoverAtFraction(canvasElement, 0.5),
}

// Formula series have no `action`; their `order` and `series_name` keep the repeated
// breakdown values from separate formulas attributable.
export const MultipleFormulasWithBreakdown: Story = {
    render: () => (
        <TooltipChart
            fixtures={[
                {
                    label: 'true',
                    data: [45, 82, 134, 210, 95],
                    seriesName: 'Formula (A+B)',
                    seriesOrder: 0,
                    breakdown_value: 'true',
                },
                {
                    label: 'false',
                    data: [20, 31, 46, 70, 38],
                    seriesName: 'Formula (A+B)',
                    seriesOrder: 0,
                    breakdown_value: 'false',
                },
                {
                    label: 'true',
                    data: [8, 12, 21, 30, 14],
                    seriesName: 'Formula (A-B)',
                    seriesOrder: 1,
                    breakdown_value: 'true',
                },
                {
                    label: 'false',
                    data: [2, 4, 5, 9, 3],
                    seriesName: 'Formula (A-B)',
                    seriesOrder: 1,
                    breakdown_value: 'false',
                },
            ]}
        />
    ),
    play: async ({ canvasElement }) => await playHoverAtFraction(canvasElement, 0.5),
}
