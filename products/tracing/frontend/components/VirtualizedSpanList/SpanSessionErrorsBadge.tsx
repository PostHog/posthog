import { IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

export interface SpanSessionErrorsBadgeProps {
    errorCount: number
    onClick: () => void
}

// The count answers the session, not the span it sits on, so the copy says "in this session"
// rather than implying the span caused the errors.
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
            onClick={(e) => {
                e.stopPropagation()
                onClick()
            }}
        />
    )
}
