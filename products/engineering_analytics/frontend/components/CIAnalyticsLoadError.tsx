import { LemonButton } from '@posthog/lemon-ui'

export function CIAnalyticsLoadError({
    onRetry,
    loading = false,
    title = "Couldn't load engineering analytics",
    description = "A GitHub source is connected, but loading its data failed. Retry, or check the source's sync status.",
}: {
    onRetry: () => void
    loading?: boolean
    title?: string
    description?: string
}): JSX.Element {
    return (
        <div className="flex flex-col items-center gap-2 py-8 text-center">
            <span className="font-medium text-danger">{title}</span>
            <span className="max-w-md text-sm text-secondary">{description}</span>
            <LemonButton
                type="primary"
                size="small"
                onClick={onRetry}
                loading={loading}
                disabledReason={loading ? 'Retrying' : undefined}
            >
                Retry
            </LemonButton>
        </div>
    )
}
