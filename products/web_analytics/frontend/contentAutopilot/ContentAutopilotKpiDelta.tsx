import clsx from 'clsx'

import { IconTrending } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'

import type { KpiDelta } from './promptReport'

export const ContentAutopilotKpiDelta = ({ delta }: { delta: KpiDelta }): JSX.Element => {
    const Icon =
        delta.direction === 'flat' ? IconTrendingFlat : delta.direction === 'up' ? IconTrending : IconTrendingDown
    return (
        <Tooltip title={delta.tooltip}>
            <span
                className={clsx(
                    'inline-flex items-center gap-0.5 text-xs whitespace-nowrap tabular-nums',
                    delta.direction === 'flat'
                        ? 'text-secondary'
                        : delta.direction === 'up'
                          ? 'text-success'
                          : 'text-danger'
                )}
            >
                <Icon />
                <span>{delta.label}</span>
            </span>
        </Tooltip>
    )
}
