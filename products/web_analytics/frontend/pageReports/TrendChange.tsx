import clsx from 'clsx'

import { IconTrending } from '@posthog/icons'

import { IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'
import { percentage } from 'lib/utils/numbers'

export function TrendChange({ change, className }: { change: number; className?: string }): JSX.Element {
    const TrendIcon = change === 0 ? IconTrendingFlat : change > 0 ? IconTrending : IconTrendingDown
    return (
        <span
            className={clsx(
                'inline-flex items-center',
                change === 0 ? 'text-secondary' : change > 0 ? 'text-success' : 'text-danger',
                className
            )}
        >
            <TrendIcon />
            <span>{percentage(Math.abs(change), 0)}</span>
        </span>
    )
}
