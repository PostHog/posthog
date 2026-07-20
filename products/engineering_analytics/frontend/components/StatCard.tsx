import { IconFilter } from '@posthog/icons'
import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import { MetricCard } from '@posthog/quill-charts'

import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'

export type StatTone = 'default' | 'danger' | 'warning' | 'success'

/** A compact right-now count: number over a small label, colored only when it's a pressure. Optionally
 *  doubles as a filter toggle (onClick + active) — the compact sibling of StatCard, shared by the hub
 *  hero and the PR list strip so both read the same. */
export function HeroStat({
    label,
    value,
    tone = 'default',
    align = 'end',
    loading = false,
    onClick,
    active = false,
    filterHint,
}: {
    label: string
    value: number | null | undefined
    tone?: StatTone
    /** 'end' in the hub hero's right cluster; 'start' in the PR list's left strip. */
    align?: 'start' | 'end'
    loading?: boolean
    onClick?: () => void
    active?: boolean
    /** What clicking filters the list to — surfaces in the tooltip. */
    filterHint?: string
}): JSX.Element {
    const pressing = value != null && value > 0
    const color =
        pressing && tone === 'danger'
            ? 'text-danger'
            : pressing && tone === 'warning'
              ? 'text-warning-dark'
              : pressing && tone === 'success'
                ? 'text-success'
                : 'text-primary'
    const alignCls = align === 'end' ? 'items-end' : 'items-start'
    const body = (
        <>
            {loading ? (
                <LemonSkeleton className="h-5 w-10" />
            ) : (
                <span className={cn('text-xl font-semibold leading-none tabular-nums', color)}>
                    {value == null ? '—' : humanFriendlyNumber(value)}
                </span>
            )}
            <span className={cn('mt-1 text-[11px] whitespace-nowrap', active ? 'text-accent' : 'text-tertiary')}>
                {label}
            </span>
        </>
    )
    if (!onClick) {
        return <div className={cn('flex flex-col', alignCls)}>{body}</div>
    }
    return (
        <Tooltip title={active ? 'Showing this view' : filterHint} placement="bottom">
            <button
                type="button"
                onClick={onClick}
                aria-pressed={active}
                className={cn(
                    'flex cursor-pointer flex-col rounded px-2.5 py-1.5 transition-colors',
                    alignCls,
                    active ? 'bg-accent-highlight-secondary' : 'hover:bg-surface-secondary'
                )}
            >
                {body}
            </button>
        </Tooltip>
    )
}

/** A headline stat that doubles as a filter toggle for the table below it. */
export function StatCard({
    label,
    value,
    caption,
    loading,
    onClick,
    active = false,
    filterHint,
}: {
    label: string
    value: string
    /** Visible definition — only when the label alone doesn't explain the count. */
    caption?: string
    loading: boolean
    onClick: () => void
    active?: boolean
    /** What clicking filters the list to — surfaces in the tooltip and hover icon. */
    filterHint: string
}): JSX.Element {
    return (
        <Tooltip title={active ? 'Showing this view' : filterHint} placement="bottom">
            <button
                type="button"
                onClick={onClick}
                aria-pressed={active}
                className={cn(
                    'group relative flex cursor-pointer flex-col gap-1 rounded-lg border p-4 text-left transition-colors',
                    active
                        ? 'border-accent bg-accent-highlight-secondary'
                        : 'border-primary bg-surface-primary hover:border-accent/40 hover:bg-surface-secondary'
                )}
            >
                <IconFilter
                    className={cn(
                        'absolute top-3 right-3 size-3.5 transition-opacity',
                        active ? 'text-accent opacity-100' : 'text-tertiary opacity-0 group-hover:opacity-100'
                    )}
                />
                {loading ? (
                    <>
                        <div className={cn('text-sm font-medium', active ? 'text-accent' : 'text-secondary')}>
                            {label}
                        </div>
                        <LemonSkeleton className="h-9 w-20" />
                    </>
                ) : (
                    <MetricCard
                        title={<span className={active ? 'text-accent' : undefined}>{label}</span>}
                        // Pre-formatted display string ('—' when no data yet) rides through the formatter.
                        value={0}
                        formatValue={() => value}
                        change={null}
                        subtitle={caption}
                    />
                )}
            </button>
        </Tooltip>
    )
}
