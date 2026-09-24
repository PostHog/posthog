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

interface CardsPreviewProps {
    loading: boolean
    setupSelected: boolean
    missingSpec: boolean
}

export function CardsPreview({
    loading: initialLoading,
    setupSelected: initialSetupSelected,
    missingSpec,
}: CardsPreviewProps): JSX.Element {
    const [loading, setLoading] = useState(initialLoading)
    const [setupSelected, setSetupSelected] = useState(initialSetupSelected)
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

    // A 960 px scene prevents component snapshots from shrinking the container-query grid to its controls.
    return (
        <div className="flex w-[60rem] max-w-full flex-col gap-4">
            <MarketingMetricCardGrid>
                {specs.map((spec) => (
                    <MarketingMetricCard
                        key={spec.kind === 'metric' ? spec.item.key : spec.key}
                        spec={missingSpec && spec.kind === 'metric' && spec.item.key === 'sessions' ? undefined : spec}
                        loading={loading}
                        labelFromKey={(key) => LABELS[key] ?? key}
                    />
                ))}
            </MarketingMetricCardGrid>
            <div className="flex flex-wrap items-center gap-2">
                <LemonButton data-attr="marketing-story-toggle-loading" onClick={() => setLoading(!loading)}>
                    {loading ? 'Show metrics' : 'Show loading'}
                </LemonButton>
                {setupSelected && <span>Goal setup selected</span>}
            </div>
        </div>
    )
}
