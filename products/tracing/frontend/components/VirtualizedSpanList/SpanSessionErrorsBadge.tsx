import { IconWarning } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

export interface SpanSessionErrorsBadgeProps {
    errorCount: number
    onClick: () => void
}

// The count answers the session, not the span it sits on, so the copy says "in this session"
// rather than implying the span caused the errors.
export function SpanSessionErrorsBadge({ errorCount, onClick }: SpanSessionErrorsBadgeProps): JSX.Element {
    return (
        <Tooltip title={`${pluralize(errorCount, 'error occurrence')} in this session. Click to see them.`}>
            <LemonButton
                size="xsmall"
                icon={<IconWarning className="text-danger" />}
                data-attr="tracing-row-session-errors"
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => {
                    e.stopPropagation()
                    onClick()
                }}
            />
        </Tooltip>
    )
}
