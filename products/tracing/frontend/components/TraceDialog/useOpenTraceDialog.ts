import { useActions } from 'kea'
import { type MouseEvent, useCallback } from 'react'

import { type OpenTraceDialogOptions, traceDialogOpenLogic } from 'lib/components/ViewTraceButton/traceDialogOpenLogic'
import type { TraceLinkParams } from 'lib/components/ViewTraceButton/traceUrl'

export type OpenTraceDialogHandler = (
    event: MouseEvent | null,
    trace: TraceLinkParams,
    options: OpenTraceDialogOptions
) => boolean

/**
 * Opens a trace in the dialog in place of navigating to Tracing. Returns false for modifier and
 * non-primary clicks, so the caller's link or navigation goes ahead. Cmd and ctrl then open Tracing
 * in a new tab, and shift opens it in place.
 */
export function useOpenTraceDialog(): OpenTraceDialogHandler {
    const { openTraceDialog } = useActions(traceDialogOpenLogic)

    // Stable across renders, so callers can list it in a memo's dependencies.
    return useCallback(
        (event, trace, options) => {
            if (event && (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0)) {
                return false
            }
            event?.preventDefault()
            openTraceDialog(trace, options)
            return true
        },
        [openTraceDialog]
    )
}
