import { useActions, useValues } from 'kea'

import { IconLive } from '@posthog/icons'
import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { logsViewerModalLogic } from 'products/logs/frontend/components/LogsViewer/LogsViewerModal/logsViewerModalLogic'
import { logsConfigLogic } from 'products/logs/frontend/logsConfigLogic'
import { buildLogsSessionFilters } from 'products/logs/frontend/utils'

export interface ViewLogsButtonProps extends Pick<LemonButtonProps, 'size' | 'type' | 'className' | 'data-attr'> {
    sessionId: string | null | undefined
    /** Scopes the logs date range around this time, so old sessions aren't hidden by the default range. */
    timestamp?: string
    iconOnly?: boolean
}

// Opens the logs viewer modal filtered to one session, using the team's configured
// session ID attribute keys. The session-replay / error-tracking counterpart of
// logs' own ViewRecordingButton usage. Gated here rather than at call sites so
// every surface of the logs-in-error-tracking rollout toggles with one flag.
export function ViewLogsButton({
    sessionId,
    timestamp,
    iconOnly,
    ...buttonProps
}: ViewLogsButtonProps): JSX.Element | null {
    const { configuredSessionIdKeys, logsConfigLoading } = useValues(logsConfigLogic)
    const { openLogsViewerModal } = useActions(logsViewerModalLogic)
    const enabled = useFeatureFlag('LOGS_IN_ERROR_TRACKING')

    if (!enabled) {
        return null
    }

    // Until the team's logs config resolves we don't know which session-ID keys to filter on.
    // Opening with the fallback key here would silently show logs filtered by the wrong
    // attribute for teams that configured a custom key, so hold the button in a loading state.
    const onClick =
        sessionId && !logsConfigLoading
            ? () =>
                  openLogsViewerModal({
                      id: `session-${sessionId}`,
                      fullScreen: false,
                      initialFilters: buildLogsSessionFilters(sessionId, configuredSessionIdKeys, timestamp),
                  })
            : undefined

    return (
        <LemonButton
            icon={<IconLive />}
            onClick={onClick}
            loading={logsConfigLoading}
            tooltip={iconOnly ? 'View logs from this session' : undefined}
            disabledReason={sessionId ? undefined : 'No session ID associated with this event'}
            {...buttonProps}
        >
            {iconOnly ? null : 'View logs'}
        </LemonButton>
    )
}
