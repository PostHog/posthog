import { useActions, useValues } from 'kea'
import { type MouseEvent, useCallback } from 'react'

import type { TraceLinkParams } from 'lib/components/ViewTraceButton/traceUrl'

import { type OpenTraceDialogOptions, traceDialogOpenLogic } from './traceDialogOpenLogic'

export type OpenTraceDialogHandler = (
    event: MouseEvent | null,
    trace: TraceLinkParams,
    options: OpenTraceDialogOptions
) => boolean

/**
 * Opens a trace in the dialog in place of navigating to Tracing. Returns false when it did not, so
 * the caller's link or navigation goes ahead: while the dialog flag is off, and for modifier and
 * non-primary clicks. Cmd and ctrl then open Tracing in a new tab, and shift opens it in place.
 */
export function useOpenTraceDialog(): OpenTraceDialogHandler {
    const { dialogEnabled } = useValues(traceDialogOpenLogic)
    const { openTraceDialog } = useActions(traceDialogOpenLogic)

    // Stable while the flag holds, so callers can list it in a memo's dependencies.
    return useCallback(
        (event, trace, options) => {
            if (!dialogEnabled) {
                return false
            }
            if (event && (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0)) {
                return false
            }
            event?.preventDefault()
            openTraceDialog(trace, options)
            return true
        },
        [dialogEnabled, openTraceDialog]
    )
}
