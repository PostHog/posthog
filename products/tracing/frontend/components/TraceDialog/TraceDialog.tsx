import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { RecordingPlayerType } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { traceUrl } from 'lib/components/ViewTraceButton/traceUrl'

import { TraceIdentityChips } from 'products/tracing/frontend/components/TraceDrawer/TraceIdentityChips'
import { TraceLoadErrorNotice } from 'products/tracing/frontend/components/TraceDrawer/TraceLoadErrorNotice'
import { TraceUnavailableNotice } from 'products/tracing/frontend/components/TraceDrawer/TraceUnavailableNotice'

import { TraceView } from '../TraceView/TraceView'
import { TraceViewDrawer } from '../TraceView/TraceViewDrawer'
import { traceViewLogic } from '../TraceView/traceViewLogic'
import { TraceViewShortcuts } from '../TraceView/TraceViewShortcuts'
import { TRACE_DIALOG_DATA_ATTR, TRACE_DIALOG_VIEW_ID, traceDialogLogic } from './traceDialogLogic'
import { TraceDialogOpenedFromLog } from './TraceDialogOpenedFromLog'

export function TraceDialog(): JSX.Element | null {
    const {
        isOpen,
        trace,
        traceSpans,
        traceSpansLoading,
        traceSpansFailed,
        sessionErrorBadgesEnabled,
        traceIdentity,
        traceSessionId,
        inspectorOpen,
        isFullscreen,
        openedFrom,
        openedAtUs,
    } = useValues(traceDialogLogic)
    const { closeTraceDialog, loadTraceSpans, openInTracing, toggleInspector, toggleFullscreen } =
        useActions(traceDialogLogic)
    const { summary } = useValues(traceViewLogic({ id: TRACE_DIALOG_VIEW_ID }))

    if (!trace) {
        return null
    }

    return (
        <TraceViewDrawer
            viewId={TRACE_DIALOG_VIEW_ID}
            traceId={trace.traceId}
            isOpen={isOpen}
            // The close button hands onClose its click event, which must not land in the reason argument.
            onClose={() => closeTraceDialog('dismissed')}
            inspectorOpen={inspectorOpen}
            onToggleInspector={toggleInspector}
            isFullscreen={isFullscreen}
            onToggleFullscreen={toggleFullscreen}
            // Logs and metrics open it from inside their own modals and popovers.
            forceAbovePopovers
            shortcuts={
                <TraceViewShortcuts closeLabel={openedFrom ? 'Back to log' : 'Close'}>
                    <span className="flex items-center gap-1">
                        <KeyboardShortcut command />
                        <span>Click Open in Tracing for a new tab</span>
                    </span>
                </TraceViewShortcuts>
            }
            footerActions={
                <LemonButton
                    type="secondary"
                    icon={<IconExternal />}
                    to={traceUrl(trace)}
                    onClick={openInTracing}
                    data-attr="trace-dialog-open-in-tracing"
                >
                    Open in Tracing
                </LemonButton>
            }
            data-attr={TRACE_DIALOG_DATA_ATTR}
        >
            <TraceDialogOpenedFromLog />
            <TraceIdentityChips
                identity={traceIdentity}
                timestamp={summary.rootSpan?.timestamp ?? trace.ts ?? null}
                // The player modal stacks below this drawer, so the recording opens in a new tab.
                openRecordingIn={RecordingPlayerType.NewTab}
            />
            {traceSpans?.truncated && (
                <LemonBanner type="info">
                    Showing the first {summary.spanCount.toLocaleString()} spans. Open this trace in Tracing to see all
                    of them.
                </LemonBanner>
            )}
            {traceSpansLoading ? (
                <div className="flex flex-1 items-center justify-center">
                    <Spinner className="text-2xl" />
                </div>
            ) : traceSpansFailed ? (
                <TraceLoadErrorNotice onRetry={() => loadTraceSpans(trace)} />
            ) : !traceSpans || traceSpans.spans.length === 0 ? (
                // There are no filters here, and Open in Tracing below covers spans outside this time window.
                <TraceUnavailableNotice traceId={trace.traceId} filtersActive={false} surface="trace_dialog" />
            ) : (
                <TraceView
                    traceId={trace.traceId}
                    inspectorOpen={inspectorOpen}
                    sessionId={traceSessionId}
                    showErrorsTab={sessionErrorBadgesEnabled}
                    openedFrom={openedFrom}
                    openedAtUs={openedAtUs}
                />
            )}
        </TraceViewDrawer>
    )
}
