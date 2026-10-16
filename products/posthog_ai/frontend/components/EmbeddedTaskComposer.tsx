import { ReactNode, Suspense } from 'react'

import { Spinner } from 'lib/lemon-ui/Spinner'
import { lazyWithRetry } from 'lib/utils/retryImport'

import type { EmbeddedTaskComposerImplProps } from '../scenes/TaskTracker/components/EmbeddedTaskComposerImpl'

export type EmbeddedTaskComposerProps = EmbeddedTaskComposerImplProps & {
    /** Shown while the composer chunk loads. A host passes a placeholder shaped like the composer. */
    fallback?: ReactNode
}

// The composer pulls in the TaskTracker scene logic and its pickers, so it loads on demand. A host that
// only imports this module keeps its own chunk light.
const Lazy = lazyWithRetry(() =>
    import('../scenes/TaskTracker/components/EmbeddedTaskComposerImpl').then((m) => ({
        default: m.EmbeddedTaskComposerImpl,
    }))
)

/** The new-task composer (repository, mode, model and effort pickers, attachments, context) without the run view. */
export function EmbeddedTaskComposer({ fallback, ...props }: EmbeddedTaskComposerProps): JSX.Element {
    return (
        <Suspense
            fallback={
                fallback ?? (
                    <div className="flex items-center justify-center py-6">
                        <Spinner className="text-2xl" />
                    </div>
                )
            }
        >
            <Lazy {...props} />
        </Suspense>
    )
}
