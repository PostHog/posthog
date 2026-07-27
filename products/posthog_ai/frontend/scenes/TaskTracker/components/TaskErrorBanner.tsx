import { LemonBanner } from '@posthog/lemon-ui'

export interface TaskErrorBannerProps {
    /** Headline line, e.g. "We couldn't load this task." */
    title: string
    /** Detail line — the resolved API error message. */
    message: string
    onRetry: () => void
    dataAttr: string
    className?: string
}

/** Reusable error + retry banner for the task scene's failed loads (task, runs, selected run). */
export function TaskErrorBanner({ title, message, onRetry, dataAttr, className }: TaskErrorBannerProps): JSX.Element {
    return (
        <LemonBanner
            type="error"
            className={className}
            action={{ children: 'Retry', onClick: onRetry }}
            data-attr={dataAttr}
        >
            <p>{title}</p>
            <p className="text-muted mb-0">{message}</p>
        </LemonBanner>
    )
}
