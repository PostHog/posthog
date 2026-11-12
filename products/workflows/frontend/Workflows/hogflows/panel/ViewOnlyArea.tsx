import './ViewOnlyArea.scss'

import { useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { workflowLogic } from '../../workflowLogic'

const READING_CONTROLS =
    '.LemonCollapsePanel__header, .ViewOnlyArea__reading-control, a[href], [data-attr="copy-code-button"], [data-attr^="show-prop-filter-"], [data-attr="workflow-schedule-row"], [data-attr="warehouse-column-copy"]'
const FOCUS_KEYS = new Set(['Tab', 'Escape'])
const TEXT_CURSOR_KEYS = new Set([
    'ArrowUp',
    'ArrowDown',
    'ArrowLeft',
    'ArrowRight',
    'Home',
    'End',
    'PageUp',
    'PageDown',
])
const CODE_LINE_MOVE_KEYS = new Set(['ArrowUp', 'ArrowDown'])
const TEXT_FIELDS =
    'textarea, input:not([type]), input[type="text"], input[type="search"], input[type="email"], input[type="url"], .monaco-editor'
const READING_SHORTCUTS = new Set(['a', 'c'])

function isReadingControl(event: React.SyntheticEvent): boolean {
    return event.target instanceof Element && event.target.closest(READING_CONTROLS) !== null
}

function blockEditing(event: React.SyntheticEvent): void {
    if (!isReadingControl(event)) {
        event.preventDefault()
        event.stopPropagation()
    }
}

function isInTextField(event: React.SyntheticEvent): boolean {
    return event.target instanceof Element && event.target.closest(TEXT_FIELDS) !== null
}

function isCodeLineMoveOrCopy(event: React.KeyboardEvent): boolean {
    return (
        event.altKey &&
        CODE_LINE_MOVE_KEYS.has(event.key) &&
        event.target instanceof Element &&
        event.target.closest('.monaco-editor') !== null
    )
}

function isCursorMove(event: React.KeyboardEvent): boolean {
    return TEXT_CURSOR_KEYS.has(event.key) && !isCodeLineMoveOrCopy(event) && isInTextField(event)
}

function isReadingShortcut(event: React.KeyboardEvent): boolean {
    return (
        (event.metaKey || event.ctrlKey) &&
        !event.altKey &&
        !event.shiftKey &&
        READING_SHORTCUTS.has(event.key.toLowerCase())
    )
}

function isReadingKey(event: React.KeyboardEvent): boolean {
    return FOCUS_KEYS.has(event.key) || isCursorMove(event) || isReadingShortcut(event)
}

function isFindShortcut(event: React.KeyboardEvent): boolean {
    return (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey && event.key.toLowerCase() === 'f'
}

function isCodeEditorTab(event: React.KeyboardEvent): boolean {
    return event.key === 'Tab' && event.target instanceof Element && event.target.closest('.monaco-editor') !== null
}

function blockEditingKeys(event: React.KeyboardEvent): void {
    if (isFindShortcut(event) || isCodeEditorTab(event)) {
        event.stopPropagation()
        return
    }
    if (!isReadingKey(event)) {
        blockEditing(event)
    }
}

function blockNativeBeforeInput(event: Event): void {
    event.preventDefault()
}

export function ViewOnlyArea({ children }: { children: React.ReactNode }): JSX.Element {
    const { isViewOnly } = useValues(workflowLogic)
    const areaRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        const area = areaRef.current
        if (!isViewOnly || !area) {
            return
        }
        area.addEventListener('beforeinput', blockNativeBeforeInput, true)
        return () => area.removeEventListener('beforeinput', blockNativeBeforeInput, true)
    }, [isViewOnly])

    return (
        <div
            ref={areaRef}
            data-view-only={isViewOnly || undefined}
            onClickCapture={isViewOnly ? blockEditing : undefined}
            onKeyDownCapture={isViewOnly ? blockEditingKeys : undefined}
            onPasteCapture={isViewOnly ? blockEditing : undefined}
            onCutCapture={isViewOnly ? blockEditing : undefined}
            onContextMenuCapture={isViewOnly ? blockEditing : undefined}
            onDropCapture={isViewOnly ? blockEditing : undefined}
            className="ViewOnlyArea contents"
        >
            {children}
        </div>
    )
}
