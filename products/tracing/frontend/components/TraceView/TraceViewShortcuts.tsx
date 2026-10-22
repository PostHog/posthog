import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'

export interface TraceViewShortcutsProps {
    /** What Escape does here, such as "Close" or "Back to log". */
    closeLabel: string
    children?: React.ReactNode
}

export function TraceViewShortcuts({ closeLabel, children }: TraceViewShortcutsProps): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
            <span className="flex items-center gap-1">
                <KeyboardShortcut escape />
                <span>{closeLabel}</span>
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
            {children}
        </div>
    )
}
