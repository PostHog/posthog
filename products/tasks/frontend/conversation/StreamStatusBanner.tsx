import { LemonBanner } from '@posthog/lemon-ui'

interface StreamStatusBannerProps {
    onRetry?: () => void
}

export default function StreamStatusBanner({ onRetry }: StreamStatusBannerProps): JSX.Element {
    return (
        <LemonBanner
            type="warning"
            className="shrink-0"
            square
            hideIcon={false}
            action={onRetry ? { children: 'Retry', onClick: onRetry } : undefined}
        >
            <div className="flex min-w-0 items-baseline gap-2">
                <span className="shrink-0 font-medium">Cloud stream disconnected</span>
                <span className="truncate text-sm text-muted">Live updates are paused — retry to reconnect.</span>
            </div>
        </LemonBanner>
    )
}
