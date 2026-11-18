import { LemonTag } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

/** Marks an observation the viewer hasn't opened; the caller positions it over a thumbnail. */
export function UnviewedObservationTag({ className }: { className?: string }): JSX.Element {
    return (
        <LemonTag
            type="primary"
            size="small"
            // The primary tag is transparent by default, which lets the frame show through.
            className={cn('shadow-sm bg-surface-primary!', className)}
            title="You haven't opened this observation yet."
        >
            New
        </LemonTag>
    )
}
