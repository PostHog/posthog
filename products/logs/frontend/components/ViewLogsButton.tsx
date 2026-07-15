import { useValues } from 'kea'

import { IconLive } from '@posthog/icons'
import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

import { logsConfigLogic } from 'products/logs/frontend/logsConfigLogic'
import { buildLogsSessionUrl } from 'products/logs/frontend/utils'

export interface ViewLogsButtonProps extends Pick<LemonButtonProps, 'size' | 'type' | 'className' | 'data-attr'> {
    sessionId: string | null | undefined
    /** Scopes the logs date range around this time, so old sessions aren't hidden by the default range. */
    timestamp?: string
    iconOnly?: boolean
}

// Links into the logs scene filtered to one session, using the team's configured
// session ID attribute keys. The session-replay / error-tracking counterpart of
// logs' own ViewRecordingButton usage.
export function ViewLogsButton({ sessionId, timestamp, iconOnly, ...buttonProps }: ViewLogsButtonProps): JSX.Element {
    const { configuredSessionIdKeys } = useValues(logsConfigLogic)

    return (
        <LemonButton
            icon={<IconLive />}
            to={sessionId ? buildLogsSessionUrl(sessionId, configuredSessionIdKeys, timestamp) : undefined}
            targetBlank
            tooltip={iconOnly ? 'View logs from this session' : undefined}
            disabledReason={sessionId ? undefined : 'No session ID associated with this event'}
            {...buttonProps}
        >
            {iconOnly ? null : 'View logs'}
        </LemonButton>
    )
}
