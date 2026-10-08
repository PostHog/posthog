import clsx from 'clsx'

import { rankingLiftBarPercent } from './rankingFormat'

/** A lift on a log scale with a tick at 1x. A head without a lift shows an empty track. */
export function RankingLiftBar({ lift, className }: { lift: number | null; className?: string }): JSX.Element {
    return (
        <span className="relative block h-1.5 overflow-hidden rounded-full">
            {/* The track and tick take the text color, so they keep contrast in a dark tooltip and on a light card. */}
            <span className="absolute inset-0 bg-current opacity-20" aria-hidden />
            {lift !== null ? (
                <span
                    className={clsx('relative block h-full rounded-full', className ?? 'bg-current')}
                    // oxlint-disable-next-line react/forbid-dom-props
                    style={{ width: `${rankingLiftBarPercent(lift)}%` }}
                />
            ) : null}
            <span className="absolute inset-y-0 left-1/2 w-px bg-current opacity-60" aria-hidden />
        </span>
    )
}
