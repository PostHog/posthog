import { Card, CardContent, Skeleton } from '@posthog/quill-primitives'

import { formatPercentage } from 'lib/utils/numbers'

import { type LabShare } from './leaderboardShares'

const PODIUM_SIZE = 3

export function LabScoreboard({ shares, loading }: { shares: LabShare[]; loading: boolean }): JSX.Element | null {
    if (loading && shares.length === 0) {
        return <Skeleton className="h-20 w-full" />
    }
    if (shares.length === 0) {
        return null
    }
    return (
        <div className="grid min-w-0 grid-cols-1 gap-4 @min-[40rem]/mcp-overview:grid-cols-3">
            {shares.slice(0, PODIUM_SIZE).map(({ lab, share }) => (
                <Card key={lab} size="sm" data-attr="mcp-leaderboard-lab-tile">
                    <CardContent className="flex flex-col gap-1">
                        <span className="text-sm text-secondary">{lab}</span>
                        <span className="text-3xl font-semibold tabular-nums text-primary">
                            {formatPercentage(share, { compact: true })}
                        </span>
                        <span className="text-xs text-secondary">of calls from models that name themselves</span>
                    </CardContent>
                </Card>
            ))}
        </div>
    )
}
