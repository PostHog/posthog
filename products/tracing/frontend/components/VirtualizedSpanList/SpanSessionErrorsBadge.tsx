import { IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

export interface SpanSessionErrorsBadgeProps {
    errorCount: number
    onClick: () => void
}

export function SpanSessionErrorsBadge({ errorCount, onClick }: SpanSessionErrorsBadgeProps): JSX.Element {
    const label = `${pluralize(errorCount, 'error occurrence')} in this session`

    return (
        <LemonButton
            size="xsmall"
            icon={<IconWarning className="text-danger" />}
            tooltip={`${label}. Click to see them.`}
            aria-label={label}
            data-attr="tracing-row-session-errors"
            onMouseDown={(e) => e.stopPropagation()}
            // The row behind this button activates on Enter and Space too, and it calls
            // preventDefault, which would cancel the click this button is about to fire. Keep the
            // key press here so the badge opens the Errors tab rather than the row's own target.
            onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.stopPropagation()
                }
            }}
            onClick={(e) => {
                e.stopPropagation()
                onClick()
            }}
        />
    )
}
