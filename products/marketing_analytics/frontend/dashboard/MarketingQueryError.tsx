import { LemonBanner } from '@posthog/lemon-ui'

export function MarketingQueryError({
    message,
    queryId,
    onRetry,
    loading = false,
}: {
    message: string
    queryId: string | null | undefined
    onRetry: () => void
    loading?: boolean
}): JSX.Element {
    return (
        <LemonBanner
            type="error"
            action={{ children: 'Retry', onClick: onRetry, loading, 'data-attr': 'marketing-query-error-retry' }}
        >
            <span>{message}</span>
            {queryId && (
                <div className="text-muted text-xs break-all">
                    <span>Query ID: </span>
                    <span className="font-mono" translate="no">
                        {queryId}
                    </span>
                </div>
            )}
        </LemonBanner>
    )
}
