import { LemonButton } from '@posthog/lemon-ui'

/**
 * Generic, retryable error state for the CI analytics scenes. Distinct from
 * ConnectGitHubSource: shown when a source IS connected but its data endpoints failed
 * (e.g. a 500), so a connected team is never wrongly told to connect a source.
 */
export function CIAnalyticsLoadError({ onRetry }: { onRetry: () => void }): JSX.Element {
    return (
        <div className="flex flex-col items-center gap-2 py-12 text-center">
            <span className="font-medium text-danger">Couldn't load CI analytics</span>
            <span className="max-w-md text-sm text-secondary">
                A GitHub source is connected, but its data endpoints returned an error — this isn't a missing source.
                Retry, or check the source's sync status.
            </span>
            <LemonButton type="primary" size="small" onClick={onRetry}>
                Retry
            </LemonButton>
        </div>
    )
}
