import { useValues } from 'kea'

import { KeyboardShortcut } from 'lib/lemon-ui/KeyboardShortcut/KeyboardShortcut'

import { tracingConfigLogic } from 'products/tracing/frontend/tracingConfigLogic'

export interface TraceViewShortcutsProps {
    /** What Escape does here, such as "Close" or "Back to log". */
    closeLabel: string
    children?: React.ReactNode
}

export function TraceViewShortcuts({ closeLabel, children }: TraceViewShortcutsProps): JSX.Element {
    // The span keys are off while the call tree hides the span tree, so their hints go with them.
    const { traceViewMode } = useValues(tracingConfigLogic)
    return (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
            <span className="flex items-center gap-1">
                <KeyboardShortcut escape />
                <span>{closeLabel}</span>
            </span>
            {traceViewMode !== 'calltree' && (
                <>
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
                </>
            )}
            {children}
        </div>
    )
}
