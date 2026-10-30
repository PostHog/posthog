import { useActions } from 'kea'

import { IconLive } from '@posthog/icons'
import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import {
    LogsViewerModalOrigin,
    logsViewerModalLogic,
} from 'products/logs/frontend/components/LogsViewer/LogsViewerModal/logsViewerModalLogic'
import { buildLogsSessionScope } from 'products/logs/frontend/utils'

export interface ViewLogsButtonProps extends Pick<LemonButtonProps, 'size' | 'type' | 'className' | 'data-attr'> {
    sessionId: string | null | undefined
    /** Scopes the logs date range around this time, so old sessions aren't hidden by the default range. */
    timestamp?: string
    /** Names where the modal was opened from, so it can say so and offer a way back. */
    openedFrom: LogsViewerModalOrigin
    iconOnly?: boolean
}

export function useViewLogsButton({
    sessionId,
    timestamp,
    openedFrom,
}: Pick<ViewLogsButtonProps, 'sessionId' | 'timestamp' | 'openedFrom'>): {
    enabled: boolean
    onClick: (() => void) | undefined
    disabledReason: string | undefined
} {
    const { openLogsViewerModal } = useActions(logsViewerModalLogic)
    const enabled = useFeatureFlag('LOGS_IN_ERROR_TRACKING')

    const onClick = sessionId
        ? () =>
              openLogsViewerModal({
                  id: `session-${sessionId}`,
                  fullScreen: false,
                  openedFrom,
                  ...buildLogsSessionScope(sessionId, timestamp),
              })
        : undefined

    return {
        enabled,
        onClick,
        disabledReason: sessionId ? undefined : 'No session ID associated with this event',
    }
}

// The shared hook keeps the feature flag and the session scope consistent across every logs entry point.
export function ViewLogsButton({
    sessionId,
    timestamp,
    openedFrom,
    iconOnly,
    ...buttonProps
}: ViewLogsButtonProps): JSX.Element | null {
    const { enabled, onClick, disabledReason } = useViewLogsButton({ sessionId, timestamp, openedFrom })

    if (!enabled) {
        return null
    }

    return (
        <LemonButton
            icon={<IconLive />}
            onClick={onClick}
            tooltip={iconOnly ? 'View logs from this session' : undefined}
            disabledReason={disabledReason}
            {...buttonProps}
        >
            {iconOnly ? null : 'View logs'}
        </LemonButton>
    )
}
