import { Spinner } from '@posthog/lemon-ui'

export function AIDataLoading({ variant = 'inline' }: { variant?: 'inline' | 'block' }): JSX.Element {
    if (variant === 'inline') {
        return (
            <div className="inline-flex items-center gap-1 text-muted-alt">
                <Spinner className="text-sm" />
                <span className="text-xs">Loading...</span>
            </div>
        )
    }

    return (
        <div className="flex flex-col items-center justify-center p-8 text-muted-alt">
            <Spinner className="text-2xl mb-2" />
            <p className="text-sm">Loading AI data...</p>
        </div>
    )
}
