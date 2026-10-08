import { Card, CardContent, Skeleton, ToggleGroup, ToggleGroupItem } from '@posthog/quill-primitives'

import { formatPercentage } from 'lib/utils/numbers'

import { type LabShare, type ScoreboardMetric } from './leaderboardShares'

const PODIUM_SIZE = 3

const METRICS: { value: ScoreboardMetric; label: string; caption: string }[] = [
    { value: 'calls', label: 'Calls', caption: 'of calls from models that name themselves' },
    { value: 'users', label: 'Users', caption: 'of users who called with a model from this lab' },
]

export function LabScoreboard({
    shares,
    loading,
    metric,
    onMetricChange,
}: {
    shares: LabShare[]
    loading: boolean
    metric: ScoreboardMetric
    onMetricChange: (metric: ScoreboardMetric) => void
}): JSX.Element | null {
    if (loading && shares.length === 0) {
        return <Skeleton className="h-20 w-full" />
    }
    if (shares.length === 0) {
        return null
    }
    const caption = METRICS.find(({ value }) => value === metric)?.caption
    return (
        <div className="flex min-w-0 flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs text-secondary">
                    {metric === 'users'
                        ? 'People can use models from several labs, so these do not add up to 100%.'
                        : ''}
                </span>
                <ToggleGroup
                    value={[metric]}
                    onValueChange={(next) => {
                        const [picked] = next
                        if (picked === 'calls' || picked === 'users') {
                            onMetricChange(picked)
                        }
                    }}
                    aria-label="Scoreboard metric"
                >
                    {METRICS.map(({ value, label }) => (
                        <ToggleGroupItem
                            key={value}
                            value={value}
                            size="sm"
                            data-attr={`mcp-leaderboard-lab-metric-${value}`}
                        >
                            {label}
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
            </div>
            <div className="grid min-w-0 grid-cols-1 gap-4 @min-[40rem]/mcp-overview:grid-cols-3">
                {shares.slice(0, PODIUM_SIZE).map(({ lab, share }) => (
                    <Card key={lab} size="sm" data-attr="mcp-leaderboard-lab-tile">
                        <CardContent className="flex flex-col gap-1">
                            <span className="text-sm text-secondary">{lab}</span>
                            <span className="text-3xl font-semibold tabular-nums text-primary">
                                {formatPercentage(share, { compact: true })}
                            </span>
                            <span className="text-xs text-secondary">{caption}</span>
                        </CardContent>
                    </Card>
                ))}
            </div>
        </div>
    )
}
