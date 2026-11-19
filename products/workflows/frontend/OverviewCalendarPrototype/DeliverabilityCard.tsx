import { Button } from '@posthog/quill'
// PROTOTYPE (throwaway): send health as three gauges against the limits that cut a daily send limit.
import { Gauge } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import { ChartCard } from './ChartCard'

const GAUGES = [
    {
        label: 'Bounced',
        value: 1.8,
        max: 8,
        thresholds: [
            { value: 0, color: 'var(--data-color-7)', label: 'Healthy' },
            { value: 2, color: 'var(--data-color-13)', label: 'Watch' },
            { value: 5, color: 'var(--data-color-5)', label: 'Daily limit drops' },
        ],
        decimals: 1,
    },
    {
        label: 'Spam complaints',
        value: 0.04,
        max: 0.2,
        thresholds: [
            { value: 0, color: 'var(--data-color-7)', label: 'Healthy' },
            { value: 0.08, color: 'var(--data-color-13)', label: 'Watch' },
            { value: 0.1, color: 'var(--data-color-5)', label: 'Mailbox providers block' },
        ],
        decimals: 2,
    },
    {
        label: 'Unsubscribed',
        value: 0.21,
        max: 2,
        thresholds: [
            { value: 0, color: 'var(--data-color-7)', label: 'Healthy' },
            { value: 0.5, color: 'var(--data-color-13)', label: 'Watch' },
            { value: 1, color: 'var(--data-color-5)', label: 'High' },
        ],
        decimals: 2,
    },
]

export function DeliverabilityCard(): JSX.Element {
    const theme = useChartTheme()
    return (
        <ChartCard
            title="Deliverability"
            description="Email, last 7 days"
            action={<Button variant="link">Sending domains</Button>}
        >
            <div className="grid grid-cols-3 gap-2">
                {GAUGES.map((g) => (
                    <div key={g.label} className="flex h-32 min-w-0 flex-col">
                        <Gauge
                            value={g.value}
                            min={0}
                            max={g.max}
                            thresholds={g.thresholds}
                            theme={theme}
                            label={g.label}
                            config={{ valueFormatter: (v) => `${v.toFixed(g.decimals)}%` }}
                        />
                    </div>
                ))}
            </div>
        </ChartCard>
    )
}
