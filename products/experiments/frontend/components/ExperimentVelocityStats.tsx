import { useValues } from 'kea'

import { IconInfo, IconTrending } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { IconTrendingDown } from 'lib/lemon-ui/icons'

import { experimentsLogic } from 'products/experiments/frontend/scenes/experimentsLogic'

export const VELOCITY_HELP =
    "Shows your team's experimentation velocity: how many experiments you're launching, running, and completing. Launched count is compared to the previous 30 days to track growth."

export interface ExperimentVelocity {
    launched: number
    percentChange: number
    running: number
    completed: number
}

/** The velocity numbers, or null while they load or when too few experiments launched for them to mean much. */
export function useExperimentVelocity(): ExperimentVelocity | null {
    const { experimentsStats, experimentsStatsLoading } = useValues(experimentsLogic)

    if (experimentsStatsLoading || !experimentsStats || experimentsStats.launched_last_30d <= 3) {
        return null
    }

    return {
        launched: experimentsStats.launched_last_30d,
        percentChange: experimentsStats.percent_change,
        running: experimentsStats.active_experiments,
        completed: experimentsStats.completed_last_30d,
    }
}

export function ExperimentVelocityStats(): JSX.Element | null {
    const velocity = useExperimentVelocity()

    if (!velocity) {
        return null
    }

    const {
        launched: launched_last_30d,
        percentChange: percent_change,
        running: active_experiments,
        completed: completed_last_30d,
    } = velocity

    const isPositive = percent_change > 0
    const isNegative = percent_change < 0
    const arrow = isPositive ? <IconTrending fontSize="14" /> : isNegative ? <IconTrendingDown fontSize="14" /> : ''
    const changeColor = isPositive ? 'text-success' : isNegative ? 'text-danger' : 'text-text-secondary'

    return (
        <div className="px-4 py-2 border rounded bg-bg-light flex items-center gap-4">
            <div className="metric-cell-header font-semibold flex items-center gap-1">
                Velocity
                <Tooltip title={VELOCITY_HELP}>
                    <IconInfo className="text-muted-alt" fontSize="16" />
                </Tooltip>
            </div>
            <div className="h-8 w-px bg-border" />
            <div className="flex items-center gap-7">
                <div className="flex flex-col">
                    <div className="flex items-center gap-1.5">
                        <span className="text-base font-semibold leading-5">{launched_last_30d}</span>
                        {percent_change !== 0 && (
                            <span className={`text-xs font-medium flex items-center gap-0.5 ${changeColor}`}>
                                {arrow}
                                {Math.abs(percent_change)}%
                            </span>
                        )}
                    </div>
                    <span className="text-xs text-text-secondary leading-4 whitespace-nowrap">launched (30d)</span>
                </div>
                <div className="flex flex-col">
                    <span className="text-base font-semibold leading-5">{active_experiments}</span>
                    <span className="text-xs text-text-secondary leading-4">running</span>
                </div>
                <div className="flex flex-col">
                    <span className="text-base font-semibold leading-5">{completed_last_30d}</span>
                    <span className="text-xs text-text-secondary leading-4">completed</span>
                </div>
            </div>
        </div>
    )
}
