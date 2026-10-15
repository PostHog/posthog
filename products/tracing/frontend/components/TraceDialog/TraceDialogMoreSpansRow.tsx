import { LemonButton } from '@posthog/lemon-ui'

import type { TraceDialogRow } from './traceDialogRows'
import { indentPx, TraceDialogTreeLines } from './TraceDialogTreeLines'

export interface TraceDialogMoreSpansRowProps {
    row: Extract<TraceDialogRow, { kind: 'more' }>
    onShowAll: (spanId: string) => void
}

export function TraceDialogMoreSpansRow({ row, onShowAll }: TraceDialogMoreSpansRowProps): JSX.Element {
    const { parent, hiddenCount } = row
    return (
        <div className="flex items-center w-full h-full gap-2 text-xs text-muted border-l-[3px] border-l-transparent">
            <span className="w-16 shrink-0" aria-hidden />
            <span
                className="relative self-stretch w-96 shrink-0 flex items-center gap-2"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ paddingLeft: indentPx(row.depth) + 22 }}
            >
                <TraceDialogTreeLines row={row} />
                <span className="relative">
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
