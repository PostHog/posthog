import { LemonCard } from '@posthog/lemon-ui'

export interface RequestUsageSummaryCardProps {
    label: string
    value: number
}

export function RequestUsageSummaryCard({ label, value }: RequestUsageSummaryCardProps): JSX.Element {
    return (
        <LemonCard className="p-4">
            <div className="text-secondary">{label}</div>
            <div className="text-2xl font-semibold tabular-nums">{value.toLocaleString()}</div>
        </LemonCard>
    )
}
