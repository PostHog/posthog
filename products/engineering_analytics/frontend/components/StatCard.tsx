import { LemonSkeleton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

export function StatCard({
    label,
    value,
    caption,
    loading,
    onClick,
    active = false,
}: {
    label: string
    value: string
    caption: string
    loading: boolean
    /** When set, the card acts as a filter toggle for the table below it. */
    onClick?: () => void
    active?: boolean
}): JSX.Element {
    const content = (
        <>
            <div className={cn('text-xs', active ? 'font-medium text-accent' : 'text-secondary')}>{label}</div>
            {loading ? (
                <LemonSkeleton className="h-8 w-20" />
            ) : (
                <div className="text-2xl font-bold leading-tight">{value}</div>
            )}
            <div className="text-xs text-tertiary">{caption}</div>
        </>
    )

    if (!onClick) {
        return <div className="flex flex-col gap-1 rounded-lg border bg-surface-primary p-4">{content}</div>
    }

    return (
        <button
            type="button"
            onClick={onClick}
            aria-pressed={active}
            className={cn(
                'flex cursor-pointer flex-col gap-1 rounded-lg border p-4 text-left transition-colors',
                active
                    ? 'border-accent bg-accent-highlight-secondary'
                    : 'border-primary bg-surface-primary hover:border-accent/40 hover:bg-surface-secondary'
            )}
        >
            {content}
        </button>
    )
}
