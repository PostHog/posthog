import clsx from 'clsx'
import { ReactNode } from 'react'

import { SpinnerOverlay } from '@posthog/lemon-ui'

export function SearchAndAiLoading({
    loading,
    label = 'Updating…',
    className,
    children,
}: {
    loading: boolean
    label?: string
    className?: string
    children?: ReactNode
}): JSX.Element {
    return (
        <div
            className={clsx(
                'SearchAndAiLoading relative isolate min-w-0 flex flex-col flex-1',
                loading && 'SearchAndAiLoading--active',
                className
            )}
            aria-busy={loading}
        >
            {children}
            {loading && (
                <div role="status" aria-label={label}>
                    <SpinnerOverlay />
                    <span className="sr-only">{label}</span>
                </div>
            )}
        </div>
    )
}
