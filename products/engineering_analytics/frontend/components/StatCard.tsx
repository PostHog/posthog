import { IconFilter } from '@posthog/icons'
import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import { MetricCard } from '@posthog/quill-charts'

import { cn } from 'lib/utils/css-classes'

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
