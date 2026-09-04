import { IconWarning } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

export interface SessionErrorsBadgeProps {
    errorCount: number
    onClick: () => void
}

// The count answers the session, not the log line it sits on, so the copy says "in this session"
// rather than implying the log caused the errors.
export function SessionErrorsBadge({ errorCount, onClick }: SessionErrorsBadgeProps): JSX.Element {
    return (
        <Tooltip title={`${pluralize(errorCount, 'error')} in this session. Click to see them.`}>
            <LemonButton
                size="xsmall"
                icon={<IconWarning className="text-danger" />}
                data-attr="logs-row-session-errors"
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => {
                    e.stopPropagation()
                    onClick()
                }}
            />
        </Tooltip>
    )
}
