import { LemonBanner } from '@posthog/lemon-ui'

// A failed load reads as "nothing here" without this. Show the failure and a way back, so a
// transient 500 doesn't look like an empty or broken feature.
export function VisionLoadError({
    message = "Couldn't load this data.",
    onRetry,
    className,
}: {
    message?: string
    onRetry: () => void
    className?: string
}): JSX.Element {
    return (
        <LemonBanner type="error" action={{ children: 'Try again', onClick: onRetry }} className={className}>
            {message}
        </LemonBanner>
    )
}
