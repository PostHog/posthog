import { useValues } from 'kea'

import { workflowLogic } from '../../workflowLogic'

const READING_CONTROLS = '.LemonCollapsePanel__header, a[href]'
const READING_KEYS = new Set(['Tab', 'Escape'])

function isReadingControl(event: React.SyntheticEvent): boolean {
    return event.target instanceof Element && event.target.closest(READING_CONTROLS) !== null
}

function blockEditing(event: React.SyntheticEvent): void {
    if (!isReadingControl(event)) {
        event.preventDefault()
        event.stopPropagation()
    }
}

function blockEditingKeys(event: React.KeyboardEvent): void {
    if (!READING_KEYS.has(event.key)) {
        blockEditing(event)
    }
}

// A disabled <fieldset> would also disable collapse headers, and viewers need those to read nested settings.
// Some step controls call APIs directly, so events are blocked here and not only in workflowLogic.
export function ViewOnlyArea({ children }: { children: React.ReactNode }): JSX.Element {
    const { isViewOnly } = useValues(workflowLogic)

    return (
        <div
            data-view-only={isViewOnly || undefined}
            onClickCapture={isViewOnly ? blockEditing : undefined}
            onKeyDownCapture={isViewOnly ? blockEditingKeys : undefined}
            onPasteCapture={isViewOnly ? blockEditing : undefined}
            onDropCapture={isViewOnly ? blockEditing : undefined}
            className="contents [&[data-view-only]_:is(input,textarea,select,button,.monaco-editor):not(.LemonCollapsePanel\_\_header)]:pointer-events-none [&[data-view-only]_:is(input,textarea,select,button,.monaco-editor):not(.LemonCollapsePanel\_\_header)]:opacity-60"
        >
            {children}
        </div>
    )
}
