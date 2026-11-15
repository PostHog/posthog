import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { LogTag } from 'products/logs/frontend/components/LogTag'
import { formatDuration } from 'products/tracing/frontend/TraceWaterfallView'

import { traceViewLogic } from '../TraceView/traceViewLogic'
import { TRACE_DIALOG_VIEW_ID, traceDialogLogic } from './traceDialogLogic'
import { TraceDialogLogMark } from './TraceDialogLogMark'

export function TraceDialogOpenedFromLog(): JSX.Element | null {
    const { openedFrom, openedAtUs } = useValues(traceDialogLogic)
    const { closeTraceDialog } = useActions(traceDialogLogic)
    const view = traceViewLogic({ id: TRACE_DIALOG_VIEW_ID })
    const { pinnedSpan: openedSpan, timeline } = useValues(view)
    const { selectSpan } = useActions(view)

    if (!openedFrom) {
        return null
    }

    return (
        <div
            className="flex flex-wrap items-center gap-2 rounded border border-accent bg-accent-highlight-secondary px-2 py-1 text-xs"
            data-attr="trace-dialog-opened-from-log"
        >
            <span className="flex items-center gap-1.5 font-semibold">
                <TraceDialogLogMark severity={openedFrom.severity} />
                Opened from log
            </span>
            <LogTag level={openedFrom.severity} />
            <span
                className="ph-replay-block ph-no-capture font-mono truncate flex-1 basis-60 min-w-0"
                translate="no"
                title={openedFrom.body}
            >
                {openedFrom.body}
            </span>
            {openedSpan && (
                <span className="flex items-center gap-1 text-muted min-w-0 max-w-full">
                    <span className="shrink-0">Emitted by</span>
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        truncate
                        className="min-w-0"
                        onClick={() => selectSpan(openedSpan.span_id)}
                        data-attr="trace-dialog-opened-span"
                        tooltip={openedSpan.name}
                    >
                        <span className="font-mono" translate="no">
                            {openedSpan.name}
                        </span>
                    </LemonButton>
                    {openedAtUs != null && (
                        <span className="font-mono shrink-0" translate="no">
                            +{formatDuration(Math.max(openedAtUs - timeline.startUs, 0) * 1_000)}
                        </span>
                    )}
                </span>
            )}
            <LemonButton
                size="xsmall"
                type="secondary"
                onClick={() => closeTraceDialog('back_to_log')}
                data-attr="trace-dialog-back-to-log"
            >
                Back to log
            </LemonButton>
        </div>
    )
}
