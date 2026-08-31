import { IconGraph } from '@posthog/icons'
import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { traceUrl } from 'products/tracing/frontend/traceLinks'

export interface ViewTraceButtonProps extends Pick<LemonButtonProps, 'size' | 'type' | 'className' | 'data-attr'> {
    /** Hex trace id, as every product's query runner returns it. */
    traceId: string | null | undefined
    /** Anchors the waterfall on one span. */
    spanId?: string | null
    /** Bounds the cold-load lookup — OTel trace ids embed no timestamp. */
    timestamp?: string | null
    iconOnly?: boolean
}

/**
 * The shared "go to this trace" entry point, for anything that carries a trace id: a log row, an
 * error event, a metric sample. Mirrors logs' `ViewLogsButton`.
 */
export function ViewTraceButton({
    traceId,
    spanId,
    timestamp,
    iconOnly,
    ...buttonProps
}: ViewTraceButtonProps): JSX.Element | null {
    // Most rows have no trace. Rendering a link to nothing is worse than rendering nothing.
    if (!traceId) {
        return null
    }

    return (
        <LemonButton
            icon={<IconGraph />}
            to={traceUrl({ traceId, spanId, ts: timestamp })}
            tooltip={iconOnly ? 'View the trace this came from' : undefined}
            disabledReason={getAccessControlDisabledReason(
                AccessControlResourceType.Tracing,
                AccessControlLevel.Viewer
            )}
            {...buttonProps}
        >
            {iconOnly ? undefined : 'View trace'}
        </LemonButton>
    )
}
