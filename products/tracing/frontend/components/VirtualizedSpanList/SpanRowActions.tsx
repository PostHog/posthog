import { IconCopy, IconListTree } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import type { Span } from '../../types'

export interface SpanRowActionsProps {
    span: Span
    onViewTrace: () => void
}

// Always-visible row actions. The trace schema is fixed (unlike logs' configurable columns), so a
// dedicated actions column reads more clearly than a hover affordance.
export function SpanRowActions({ span, onViewTrace }: SpanRowActionsProps): JSX.Element {
    return (
        <div className="flex items-center gap-1">
            <LemonButton
                size="xsmall"
                type="secondary"
                icon={<IconListTree />}
                onClick={(e) => {
                    e.stopPropagation()
                    onViewTrace()
                }}
                tooltip="View trace waterfall"
                data-attr="tracing-view-trace"
            >
                View trace
            </LemonButton>
            <LemonButton
                size="xsmall"
                icon={<IconCopy />}
                onClick={(e) => {
                    e.stopPropagation()
                    void copyToClipboard(span.trace_id, 'trace ID')
                }}
                tooltip="Copy trace ID"
                aria-label="Copy trace ID"
                data-attr="tracing-copy-trace-id"
            />
        </div>
    )
}
