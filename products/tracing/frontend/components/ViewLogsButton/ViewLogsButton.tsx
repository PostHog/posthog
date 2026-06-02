import { useActions, useValues } from 'kea'

import { IconList } from '@posthog/icons'
import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { logsViewerModalLogic } from 'products/logs/frontend/components/LogsViewer/LogsViewerModal/logsViewerModalLogic'

import { buildTraceLogsFilters } from '../../logsLink'
import type { Span } from '../../types'

export interface ViewLogsButtonProps {
    span: Span
    size?: LemonButtonProps['size']
    className?: string
}

/**
 * Opens the logs for a span's trace in the Logs viewer modal (scoped to the trace, windowed, with
 * an "Open in Logs" link to the full scene). Hidden when the span has no trace id or the team
 * doesn't have logs enabled. Mirror of the logs-side `ViewTraceButton` for the reverse direction.
 */
export function ViewLogsButton({ span, size = 'xsmall', className }: ViewLogsButtonProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { openLogsViewerModal } = useActions(logsViewerModalLogic)

    if (!featureFlags[FEATURE_FLAGS.LOGS] || !span.trace_id) {
        return null
    }

    return (
        <LemonButton
            size={size}
            type="secondary"
            icon={<IconList />}
            className={className}
            data-attr="tracing-view-logs"
            onClick={() =>
                openLogsViewerModal({
                    fullScreen: false,
                    showOpenInScene: true,
                    initialFilters: buildTraceLogsFilters(span.trace_id, span.timestamp),
                })
            }
        >
            View logs
        </LemonButton>
    )
}
