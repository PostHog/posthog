// A leaderboard row: rank · label/sub · share bar · value/value-sub. The cost section builds its
// "where does it go" list from this, so every breakdown reads the same.

import { ReactNode } from 'react'

import { Link } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { Lettermark } from 'lib/lemon-ui/Lettermark'
import { cn } from 'lib/utils/css-classes'

export function ShareRow({
    rank,
    label,
    sub,
    value,
    valueSub,
    share,
    color,
    to,
    avatar,
    fullWidthBar = false,
}: {
    rank?: number
    label: ReactNode
    sub?: ReactNode
    value: ReactNode
    valueSub?: ReactNode
    /** 0–1 — the share bar's fill. Omit for a bar-less row. */
    share?: number
    color?: string
    to?: string
    avatar?: string
    /** Fixed-width label + a bar that fills the row, so bar lengths compare across rows (magnitude
     *  breakdown). Default keeps the compact narrow bar with a flexible label (leaderboard style). */
    fullWidthBar?: boolean
}): JSX.Element {
    const row = (
        <div
            className={cn(
                'flex items-center gap-3 border-b border-primary px-1 py-2 last:border-b-0',
                to && 'cursor-pointer hover:bg-fill-button-tertiary-hover'
            )}
        >
            {rank !== undefined && (
                <span className="w-4 shrink-0 text-right text-xs tabular-nums text-tertiary">{rank}.</span>
            )}
            {avatar && <Lettermark name={avatar} />}
            <span className={cn('min-w-0', fullWidthBar ? 'w-48 shrink-0' : 'flex-1')}>
                <span className="block truncate text-[13px] font-semibold text-primary">{label}</span>
                {sub && <span className="block truncate text-[11px] text-tertiary">{sub}</span>}
            </span>
            {share !== undefined && (
                <LemonProgress
                    percent={share * 100}
                    strokeColor={color ?? 'var(--brand-blue)'}
                    bgColor="var(--color-bg-fill-tertiary)"
                    smoothing={false}
                    className={fullWidthBar ? 'flex-1' : 'w-40 max-w-[30%] shrink-0'}
                />
            )}
            <span className="shrink-0 text-right">
                <span className="block text-[13px] font-semibold tabular-nums text-primary">{value}</span>
                {valueSub && <span className="block text-[10px] text-tertiary">{valueSub}</span>}
            </span>
        </div>
    )
    return to ? <Link to={to}>{row}</Link> : row
}
