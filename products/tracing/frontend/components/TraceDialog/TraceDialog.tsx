import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { traceUrl } from 'lib/components/ViewTraceButton/traceUrl'

import { traceDialogLogic } from './traceDialogLogic'

export function TraceDialog(): JSX.Element | null {
    const { isOpen, trace } = useValues(traceDialogLogic)
    const { closeTraceDialog } = useActions(traceDialogLogic)

    if (!trace) {
        return null
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeTraceDialog}
            title="Trace"
            description={<span translate="no">{trace.traceId}</span>}
            forceAbovePopovers
            width="90vw"
            maxWidth={1600}
            footer={
                <LemonButton
                    type="secondary"
                    icon={<IconExternal />}
                    to={traceUrl(trace)}
                    onClick={closeTraceDialog}
                    data-attr="trace-dialog-open-in-tracing"
                >
                    Open in Tracing
                </LemonButton>
            }
        >
            <div className="min-h-80" />
        </LemonModal>
    )
}
