import clsx from 'clsx'

import { rankingLiftBarPercent } from './rankingFormat'

/** A lift on a log scale with a tick at 1x. A head without a lift shows an empty track. */
export function RankingLiftBar({ lift, className }: { lift: number | null; className?: string }): JSX.Element {
    return (
        <span className="relative block h-1.5 overflow-hidden rounded-full bg-fill-tertiary">
            {lift !== null ? (
                <span
                    className={clsx('block h-full rounded-full', className ?? 'bg-current')}
                    // oxlint-disable-next-line react/forbid-dom-props
                    style={{ width: `${rankingLiftBarPercent(lift)}%` }}
                />
            ) : null}
            <span className="absolute inset-y-0 left-1/2 w-px bg-border-bold" aria-hidden />
        </span>
    )
}
