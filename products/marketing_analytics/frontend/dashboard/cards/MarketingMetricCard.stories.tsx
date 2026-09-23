import { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { MarketingMetricCard } from './MarketingMetricCard'
import { MarketingMetricCardGrid } from './MarketingMetricCardGrid'
import type { MetricCardSpec } from './metricCardSpec'

const LABELS: Record<string, string> = {
    sessions: 'Sessions',
    revenue: 'Revenue',
    bounce_rate: 'Bounce rate',
}

function CardsPreview({ initiallyLoading = false }: { initiallyLoading?: boolean }): JSX.Element {
    const [loading, setLoading] = useState(initiallyLoading)
    const [setupSelected, setSetupSelected] = useState(false)
    const specs: MetricCardSpec[] = [
        {
            kind: 'metric',
            item: { key: 'sessions', kind: 'unit', value: 1240, previous: 1000, changeFromPreviousPct: 24 },
        },
        {
            kind: 'notice',
            key: 'conversion_value',
            title: 'Conversion value',
            value: 'N/A',
            message: 'Choose a conversion goal with a value to see this metric.',
            action: {
                label: 'Choose a goal',
                onClick: () => setSetupSelected(true),
                dataAttr: 'marketing-story-configure-goal',
            },
        },
        {
            kind: 'metric',
            item: { key: 'revenue', kind: 'currency', value: 0, previous: 100, changeFromPreviousPct: -100 },
        },
        {
            kind: 'metric',
            item: {
                key: 'bounce_rate',
                kind: 'percentage',
                value: 30,
                previous: 40,
                changeFromPreviousPct: -25,
                isIncreaseBad: true,
            },
        },
    ]

    return (
        <div className="flex flex-col gap-4">
            <MarketingMetricCardGrid>
                {specs.map((spec) => (
                    <MarketingMetricCard
                        key={spec.kind === 'metric' ? spec.item.key : spec.key}
                        spec={spec}
                        loading={loading}
                        labelFromKey={(key) => LABELS[key] ?? key}
                    />
                ))}
            </MarketingMetricCardGrid>
            <div className="flex flex-wrap items-center gap-2">
                <LemonButton onClick={() => setLoading(!loading)}>
                    {loading ? 'Show metrics' : 'Show loading'}
                </LemonButton>
                {setupSelected && <span>Goal setup selected</span>}
            </div>
        </div>
    )
}

const meta: Meta<typeof MarketingMetricCard> = {
    title: 'Marketing Analytics/Dashboard/Metric cards',
    component: MarketingMetricCard,
}
export default meta
type Story = StoryObj<typeof meta>

export const Interactive: Story = { render: () => <CardsPreview /> }
export const Loading: Story = { render: () => <CardsPreview initiallyLoading /> }
export const Narrow: Story = {
    render: () => (
        <div className="w-[32.5rem] max-w-full">
            <CardsPreview />
        </div>
    ),
}
