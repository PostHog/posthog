import { Meta, StoryObj } from '@storybook/react'

import { CompareLabelType } from '~/types'

import { SeriesLabel } from './InsightSeriesTooltip'

const meta: Meta<typeof SeriesLabel> = {
    title: 'Insights/InsightSeriesTooltip/SeriesLabel',
    component: SeriesLabel,
    parameters: { layout: 'centered' },
    decorators: [
        (Story) => (
            // Mimic the tooltip surface so labels render in the right context.
            <div className="bg-[#1e1f26] text-white rounded-lg p-3 text-xs w-[280px]">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof SeriesLabel>

const BASE_DATUM = {
    id: 0,
    dataIndex: 0,
    datasetIndex: 0,
    order: 0,
    color: '#7c3aed',
    count: 1234,
    label: '$pageview',
    action: { id: '$pageview', name: '$pageview', type: 'events' as const, order: 0 },
}

/** Plain series name — no breakdown or compare. */
export const Plain: Story = {
    args: { datum: { ...BASE_DATUM }, hasMultipleEvents: false },
}

/** URL breakdown clips; period label is always fully visible. */
export const BreakdownCurrentPeriod: Story = {
    args: {
        datum: {
            ...BASE_DATUM,
            breakdown_value: 'https://hedgebox.net/files/019-very-long-path-that-truncates',
            compare_label: CompareLabelType.Current,
        },
        hasMultipleEvents: false,
    },
}

/** Previous period — muted period label. */
export const BreakdownPreviousPeriod: Story = {
    args: {
        datum: {
            ...BASE_DATUM,
            breakdown_value: 'https://hedgebox.net/pricing',
            compare_label: CompareLabelType.Previous,
        },
        hasMultipleEvents: false,
    },
}

/** Multiple events — event name prefix prepended in muted text. */
export const MultipleEventsWithBreakdown: Story = {
    args: {
        datum: { ...BASE_DATUM, breakdown_value: 'San Francisco', compare_label: CompareLabelType.Current },
        hasMultipleEvents: true,
    },
}

/** Custom label override — e.g. lifecycle status. */
export const LifecycleOverride: Story = {
    args: {
        datum: { ...BASE_DATUM, label: 'New' },
        hasMultipleEvents: false,
        renderSeriesOverride: (datum) => <span className="text-green-400">{datum.label}</span>,
    },
}
