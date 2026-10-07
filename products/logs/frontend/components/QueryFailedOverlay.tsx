import { IconRefresh, IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

/** Covers the pane, so it hides an empty state that would read as "no results". The parent must be `relative`. */
export function QueryFailedOverlay({
    error,
    title,
    onRetry,
    compact = false,
    className,
}: {
    error: string | null
    title: string
    onRetry: () => void
    compact?: boolean
    className?: string
}): JSX.Element | null {
    if (!error) {
        return null
    }
    return (
        <div
            className={cn(
                'absolute inset-0 z-10 flex items-center justify-center px-4 text-center',
                compact ? 'flex-row flex-wrap gap-3' : 'flex-col gap-2 py-6',
                className
            )}
            data-attr="query-failed-overlay"
        >
            <IconWarning className={cn('shrink-0 text-warning', compact ? 'text-2xl' : 'text-4xl mb-2')} />
            <div className={cn(compact && 'text-left')}>
                <h2 className={cn('m-0', compact ? 'text-sm font-semibold' : 'text-xl leading-tight mb-1')}>{title}</h2>
                <p className="m-0 max-w-120 text-sm text-muted">{error}</p>
            </div>
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconRefresh />}
                onClick={onRetry}
                className={cn(!compact && 'mt-2')}
                data-attr="query-failed-retry"
            >
                Try again
            </LemonButton>
        </div>
    )
}
