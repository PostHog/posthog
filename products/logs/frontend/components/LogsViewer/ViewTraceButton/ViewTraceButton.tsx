import { useValues } from 'kea'

import { IconLive } from '@posthog/icons'
import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { urls } from 'scenes/urls'

import { ParsedLogMessage } from 'products/logs/frontend/types'

export interface ViewTraceButtonProps {
    log: ParsedLogMessage
    size?: LemonButtonProps['size']
    noPadding?: boolean
    className?: string
    label?: string
}

/**
 * Opens the originating distributed trace in the Tracing scene. The log's timestamp scopes the
 * by-trace-id lookup (which is otherwise unbounded), and its span id auto-highlights the span.
 * Hidden when the log has no trace id or the team doesn't have tracing enabled.
 */
export function ViewTraceButton({ log, size, noPadding, className, label }: ViewTraceButtonProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.TRACING] || !log.trace_id) {
        return null
    }

    return (
        <LemonButton
            size={size}
            noPadding={noPadding}
            className={className}
            icon={<IconLive />}
            tooltip="View trace"
            aria-label="View trace"
            data-attr="logs-viewer-view-trace"
            onClick={(e) => {
                e.preventDefault()
                newInternalTab(
                    urls.tracingTrace(log.trace_id, {
                        spanId: log.span_id || undefined,
                        timestamp: log.timestamp,
                    })
                )
            }}
        >
            {label}
        </LemonButton>
    )
}
