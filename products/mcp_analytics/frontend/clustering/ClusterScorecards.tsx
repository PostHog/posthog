import { useActions, useValues } from 'kea'

import { cn } from 'lib/utils/css-classes'

import { type ClusterFilter, type RouteShapeCounts, mcpClusteringLogic } from './mcpClusteringLogic'

interface Scorecard {
    filter: Exclude<ClusterFilter, 'all'>
    label: string
    description: string
    count: (counts: RouteShapeCounts) => number
    danger?: boolean
}

const SCORECARDS: Scorecard[] = [
    {
        filter: 'concentrated',
        label: 'Concentrated',
        description: 'One tool handles at least 80% of the calls.',
        count: (c) => c.concentrated,
    },
    {
        filter: 'mixed',
        label: 'Mixed',
        description: 'The top tool handles between half and 80%.',
        count: (c) => c.mixed,
    },
    {
        filter: 'spread',
        label: 'Spread',
        description: 'No single tool handles half the calls.',
        count: (c) => c.spread,
    },
    {
        filter: 'failing',
        label: 'With errors',
        description: 'Lost at least one call to an error.',
        count: (c) => c.failing,
        danger: true,
    },
]

/**
 * Each card states how many intent groups have a routing shape, and filters the list
 * to exactly those. The counts and the filters share one predicate in the logic, so a
 * card can't report one number and show another.
 */
export function ClusterScorecards(): JSX.Element {
    const { routeShapeCounts, clusterFilter } = useValues(mcpClusteringLogic)
    const { setClusterFilter } = useActions(mcpClusteringLogic)

    return (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
            {SCORECARDS.map((card) => {
                const isActive = clusterFilter === card.filter
                const count = card.count(routeShapeCounts)
                return (
                    <button
                        key={card.filter}
                        type="button"
                        data-attr={`mcp-clustering-scorecard-${card.filter}`}
                        aria-pressed={isActive}
                        onClick={() => setClusterFilter(isActive ? 'all' : card.filter)}
                        className={cn(
                            'flex flex-col items-start rounded border p-3 text-left transition-colors',
                            isActive
                                ? 'border-accent bg-accent-highlight-secondary'
                                : 'border-primary bg-surface-primary hover:bg-accent-highlight-secondary'
                        )}
                    >
                        <span className="text-muted text-xs font-medium uppercase">{card.label}</span>
                        <span className="mt-1 flex items-baseline gap-1">
                            <span
                                className={cn(
                                    'text-2xl font-semibold tabular-nums',
                                    card.danger && count > 0 ? 'text-danger' : ''
                                )}
                            >
                                {count}
                            </span>
                            <span className="text-muted text-sm">of {routeShapeCounts.total}</span>
                        </span>
                        <span className="text-muted mt-1 text-xs">{card.description}</span>
                    </button>
                )
            })}
        </div>
    )
}
