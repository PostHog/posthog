import { useValues } from 'kea'

import { IconInfo, IconTrending } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { IconTrendingDown } from 'lib/lemon-ui/icons'

import { experimentsLogic } from 'products/experiments/frontend/scenes/experimentsLogic'

export function ExperimentVelocityStats(): JSX.Element | null {
    const { experimentsStats, experimentsStatsLoading } = useValues(experimentsLogic)

    if (experimentsStatsLoading || !experimentsStats) {
        return null
    }

    const { launched_last_30d, percent_change, active_experiments, completed_last_30d } = experimentsStats

    if (launched_last_30d <= 3) {
        return null
    }

    const isPositive = percent_change > 0
    const isNegative = percent_change < 0
    const arrow = isPositive ? <IconTrending fontSize="14" /> : isNegative ? <IconTrendingDown fontSize="14" /> : ''
    const changeColor = isPositive ? 'text-success' : isNegative ? 'text-danger' : 'text-text-secondary'

    return (
        <div className="px-4 py-2 border rounded bg-bg-light flex items-center gap-4">
            <div className="metric-cell-header font-semibold flex items-center gap-1">
                Velocity
                <Tooltip title="Shows your team's experimentation velocity: how many experiments you're launching, running, and completing. Launched count is compared to the previous 30 days to track growth.">
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
