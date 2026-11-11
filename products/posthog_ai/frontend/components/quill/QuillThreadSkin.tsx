import type { ReactNode } from 'react'

import { cn } from '@posthog/quill-primitives'

import { ThreadSkinContext } from './quillThreadContext'

export interface QuillThreadSkinProps {
    className?: string
    children: ReactNode
}

/**
 * Puts a thread that `ThreadView` does not render into the quill skin: every shared presenter below
 * (`Activity`, `ReasoningAnswer`, `AssistantFailureMessage`, `TurnFeedbackActions`) picks its quill half, and
 * the `data-quill` wrapper scopes quill's tokens and sets the text color once, as `ThreadView` does.
 */
export function QuillThreadSkin({ className, children }: QuillThreadSkinProps): JSX.Element {
    return (
        <ThreadSkinContext.Provider value="quill">
            <div data-quill className={cn('flex flex-col gap-4 text-[var(--foreground)]', className)}>
                {children}
            </div>
        </ThreadSkinContext.Provider>
    )
}
