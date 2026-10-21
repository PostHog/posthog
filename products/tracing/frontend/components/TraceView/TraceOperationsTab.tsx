import { useMemo, useState } from 'react'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { isAiEventSpan } from '../../aiEventSpans'
import { childSpansByParentId, collectSubtreeSpans } from '../../spanTree'
import { summarizeTraceOperations } from '../../traceOperations'
import type { Span } from '../../types'
import { TraceOperationsTable } from './TraceOperationsTable'

type OperationsScope = 'trace' | 'span'

export interface TraceOperationsTabProps {
    /** The inspected span. "This span" covers it and every span under it. */
    span: Span
    /** The trace's real spans. AI event rows are synthetic and have no operation of their own. */
    spans: Span[]
    highlightedOperationKey: string | null
    onHighlightOperation: (operationKey: string | null) => void
    /** The trace has spans that are not loaded yet, so the counts do not cover the whole trace. */
    partial: boolean
}

// The operations of the whole trace (default) or of the inspected span's subtree, with the same scope
// toggle as the Logs tab. The span tree highlight matches an operation across the whole trace in both scopes.
export function TraceOperationsTab({
    span,
    spans,
    highlightedOperationKey,
    onHighlightOperation,
    partial,
}: TraceOperationsTabProps): JSX.Element {
    const [scope, setScope] = useState<OperationsScope>('trace')
    // An AI row has no OTel span id, so no span has it as a parent. It stays on the trace even when the
    // user picked "This span" on a real span. The pick comes back when they select a real span.
    const spanScopeDisabledReason = isAiEventSpan(span)
        ? "AI events don't have their own span, so operations show for the whole trace"
        : undefined
    const effectiveScope: OperationsScope = spanScopeDisabledReason ? 'trace' : scope

    // Built once per span list, so that selecting another span in "This span" only walks its subtree.
    const childrenByParentId = useMemo(() => childSpansByParentId(spans), [spans])
    const scopedSpans = useMemo(
        () => (effectiveScope === 'span' ? collectSubtreeSpans(span, childrenByParentId) : spans),
        [effectiveScope, span, spans, childrenByParentId]
    )
    const { operations, spanCount } = useMemo(() => summarizeTraceOperations(scopedSpans), [scopedSpans])

    const counts = `${pluralize(operations.length, 'operation')} · ${pluralize(spanCount, 'span')}`

    return (
        <div className="flex flex-col gap-2">
            <LemonSegmentedButton
                size="xsmall"
                value={effectiveScope}
                onChange={setScope}
                options={[
                    // pinned: autocapture selects on these values, so renaming them breaks saved actions.
                    // LemonSegmentedButton puts no data-attr on its root, so each option carries one.
                    { value: 'trace', label: 'Whole trace', 'data-attr': 'tracing-operations-scope-trace' },
                    {
                        value: 'span',
                        label: 'This span',
                        disabledReason: spanScopeDisabledReason,
                        'data-attr': 'tracing-operations-scope-span',
                    },
                ]}
            />
            {/* The counts change as spans load, so they stay one text node that translation extensions skip. */}
            <span className="text-xs text-muted truncate" translate="no">
                {effectiveScope === 'span' ? `${counts} under ${span.name}` : counts}
            </span>
            <div>
                <TraceOperationsTable
                    operations={operations}
                    highlightedOperationKey={highlightedOperationKey}
                    onHighlightOperation={onHighlightOperation}
                    partial={partial}
                    compact
                    shareOf={effectiveScope}
                />
            </div>
        </div>
    )
}
