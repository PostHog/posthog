import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import type { TraceDialogRow } from './traceDialogRows'
import { indentPx, TraceDialogTreeLines } from './TraceDialogTreeLines'

export interface TraceDialogMoreSpansRowProps {
    row: Extract<TraceDialogRow, { kind: 'more' | 'fewer' }>
    /** None of the hidden spans belongs to the operation the Operations tab highlights. */
    isDimmed: boolean
    onShowAll: (spanId: string) => void
    onShowFewer: (spanId: string) => void
}

export function TraceDialogMoreSpansRow({
    row,
    isDimmed,
    onShowAll,
    onShowFewer,
}: TraceDialogMoreSpansRowProps): JSX.Element {
    const { parent } = row
    const onClick = row.kind === 'more' ? onShowAll : onShowFewer
    return (
        // Same columns and no gap as the span row, so the tree lines on both line up at any width.
        <div className="flex items-center w-full h-full text-xs text-muted border-l-[3px] border-l-transparent">
            <span className="w-16 shrink-0" aria-hidden />
            <span
                className="relative self-stretch w-96 shrink min-w-48 flex items-center gap-2"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ paddingLeft: indentPx(row.depth) + 22 }}
            >
                <TraceDialogTreeLines row={row} />
                {row.kind === 'more' && (
                    <span className={cn('relative', isDimmed && 'opacity-40')}>
                        {row.hiddenCount.toLocaleString()} more {row.hiddenCount === 1 ? 'span' : 'spans'}
                    </span>
                )}
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    onClick={() => onClick(parent.span.span_id)}
                    data-attr={row.kind === 'more' ? 'trace-dialog-show-all-spans' : 'trace-dialog-show-fewer-spans'}
                >
                    {row.kind === 'more' ? 'Show all' : 'Show fewer'}
                </LemonButton>
            </span>
            <span className="grow min-w-16" aria-hidden />
            <span className="w-20 shrink-0" aria-hidden />
        </div>
    )
}
