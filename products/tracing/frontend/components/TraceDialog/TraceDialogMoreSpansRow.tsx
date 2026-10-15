import { LemonButton } from '@posthog/lemon-ui'

import type { SpanNode } from 'products/tracing/frontend/spanTree'

import { INDENT_PX, MAX_INDENT_DEPTH } from './TraceDialogSpanRow'

export interface TraceDialogMoreSpansRowProps {
    parent: SpanNode
    hiddenCount: number
    onShowAll: (spanId: string) => void
}

export function TraceDialogMoreSpansRow({ parent, hiddenCount, onShowAll }: TraceDialogMoreSpansRowProps): JSX.Element {
    return (
        <div className="flex items-center w-full h-full gap-2 text-xs text-muted border-l-[3px] border-l-transparent">
            <span className="w-16 shrink-0" aria-hidden />
            <span
                className="flex items-center gap-2"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ paddingLeft: Math.min(parent.depth + 1, MAX_INDENT_DEPTH) * INDENT_PX }}
            >
                <span>
                    {hiddenCount.toLocaleString()} more {hiddenCount === 1 ? 'span' : 'spans'}
                </span>
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    onClick={() => onShowAll(parent.span.span_id)}
                    data-attr="trace-dialog-show-all-spans"
                >
                    Show all
                </LemonButton>
            </span>
        </div>
    )
}
