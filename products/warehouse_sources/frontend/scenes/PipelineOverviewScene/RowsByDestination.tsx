import { useValues } from 'kea'

import { LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { humanFriendlyLargeNumber, humanFriendlyNumber } from 'lib/utils/numbers'

import { pipelineOverviewSceneLogic } from './pipelineOverviewSceneLogic'

export function RowsByDestination(): JSX.Element {
    const { rowsByDestination, destinationRowTotals, destinationRowTotalsLoading, destinationsLoading } =
        useValues(pipelineOverviewSceneLogic)

    if ((destinationRowTotalsLoading && destinationRowTotals === null) || destinationsLoading) {
        return <LemonSkeleton className="h-24 w-full" />
    }

    if (rowsByDestination.length === 0) {
        return (
            <div className="rounded border border-primary bg-surface-primary px-4 py-6 text-center text-muted">
                No rows were written to a destination in this window.
            </div>
        )
    }

    // Bars are relative to the busiest destination rather than the total, so a single dominant
    // destination does not flatten every other bar to nothing.
    const busiest = Math.max(...rowsByDestination.map((row) => row.rows))

    return (
        <div className="flex flex-col gap-2 rounded border border-primary bg-surface-primary p-4">
            {rowsByDestination.map((row) => (
                <div key={row.id} className="flex flex-col gap-1">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <span className="flex items-center gap-2 min-w-0">
                            <span className="truncate font-medium">{row.name}</span>
                            <LemonTag type="muted" size="small">
                                {row.type}
                            </LemonTag>
                        </span>
                        <span className="tabular-nums font-medium" title={humanFriendlyNumber(row.rows)}>
                            {humanFriendlyLargeNumber(row.rows)}
                        </span>
                    </div>
                    <div className="h-1.5 w-full overflow-hidden rounded bg-border">
                        <div
                            className="h-full rounded bg-brand-blue"
                            // Width is the one value that has to be computed from the data.
                            style={{ width: `${Math.max(2, (row.rows / busiest) * 100)}%` }}
                        />
                    </div>
                </div>
            ))}
        </div>
    )
}
