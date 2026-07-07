import { LemonButton } from '@posthog/lemon-ui'

/**
 * Retryable error state for the engineering analytics scenes. Unlike ConnectGitHubSource, shown when a
 * source is connected but its data endpoints failed — so a connected team isn't wrongly told to connect one.
 */
export function CIAnalyticsLoadError({ onRetry }: { onRetry: () => void }): JSX.Element {
    return (
        <div className="flex flex-col items-center gap-2 py-12 text-center">
            <span className="font-medium text-danger">Couldn't load engineering analytics</span>
            <span className="max-w-md text-sm text-secondary">
                A GitHub source is connected, but loading its data failed. Retry, or check the source's sync status.
            </span>
            <LemonButton type="primary" size="small" onClick={onRetry}>
                Retry
            </LemonButton>
        </div>
    )
}
