import { useValues } from 'kea'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'

import { traceDialogLogic } from './traceDialogLogic'

export function TraceDialogShortcuts(): JSX.Element {
    const { openedFrom } = useValues(traceDialogLogic)

    return (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
            <span className="flex items-center gap-1">
                <KeyboardShortcut escape />
                <span>{openedFrom ? 'Back to log' : 'Close'}</span>
            </span>
            <span className="flex items-center gap-1">
                <KeyboardShortcut j />
                <KeyboardShortcut k />
                <span>Next or previous span</span>
            </span>
            <span className="flex items-center gap-1">
                <KeyboardShortcut arrowleft />
                <KeyboardShortcut arrowright />
                <span>Collapse or expand</span>
            </span>
            <span className="flex items-center gap-1">
                <KeyboardShortcut command />
                <span>Click Open in Tracing for a new tab</span>
            </span>
        </div>
    )
}
