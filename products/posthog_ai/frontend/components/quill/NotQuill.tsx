import type { ReactNode } from 'react'

import { cn } from '@posthog/quill-primitives'

import { useQuillThread } from './quillThreadContext'

/**
 * Fences a lemon component that has no quill skin yet, so PostHog's own colours survive inside the quill
 * thread. Renders the children bare in the lemon thread.
 */
export function NotQuill({ children, className }: { children: ReactNode; className?: string }): JSX.Element {
    const quill = useQuillThread()
    if (!quill) {
        return <>{children}</>
    }
    return (
        <div data-not-quill className={cn('min-w-0 max-w-full', className)}>
            {children}
        </div>
    )
}
