import clsx from 'clsx'

import { rankingLiftBarFill } from './rankingFormat'

/**
 * A lift on a log scale with a tick at 1x. The fill grows from the tick, right above 1x and left below 1x.
 * A head without a lift shows an empty track.
 */
export function RankingLiftBar({ lift, className }: { lift: number | null; className?: string }): JSX.Element {
    const fill = lift !== null ? rankingLiftBarFill(lift) : null
    const belowAverage = lift !== null && lift < 1
    return (
        <span className="relative block h-1.5 overflow-hidden rounded-full">
            {/* The track and tick take the text color, so they keep contrast in a dark tooltip and on a light card. */}
            <span className="absolute inset-0 bg-current opacity-20" aria-hidden />
            {fill !== null ? (
                <span
                    className={clsx(
                        'absolute inset-y-0 rounded-full',
                        className ?? 'bg-current',
                        belowAverage && 'opacity-50'
                    )}
                    // oxlint-disable-next-line react/forbid-dom-props
                    style={{ left: `${fill.left}%`, width: `${fill.width}%` }}
                />
            ) : null}
            <span className="absolute inset-y-0 left-1/2 w-px bg-current opacity-60" aria-hidden />
        </span>
    )
}
