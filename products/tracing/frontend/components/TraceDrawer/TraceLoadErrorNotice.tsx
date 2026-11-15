import { LemonButton } from '@posthog/lemon-ui'

// A failed fetch must read differently from a successful one that found nothing (TraceUnavailableNotice) —
// otherwise a network error looks like proof the trace was never sent.
export function TraceLoadErrorNotice({ onRetry }: { onRetry?: () => void }): JSX.Element {
    return (
        <div className="flex flex-col gap-1.5 p-4" data-attr="tracing-trace-load-error-notice">
            <span className="font-semibold">Couldn't load trace</span>
            <p className="m-0">PostHog couldn't load this trace.</p>
            {onRetry && (
                <div>
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={onRetry}
                        data-attr="tracing-trace-load-error-retry"
                    >
                        Try again
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
