import './ViewOnlyArea.scss'

import { useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { workflowLogic } from '../../workflowLogic'

const READING_CONTROLS = '.LemonCollapsePanel__header, a[href], [data-attr="copy-code-button"]'
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

function isReadingKey(event: React.KeyboardEvent): boolean {
    const isShortcut = event.metaKey || event.ctrlKey
    return (
        FOCUS_KEYS.has(event.key) ||
        (TEXT_CURSOR_KEYS.has(event.key) && isInTextField(event)) ||
        (isShortcut && READING_SHORTCUTS.has(event.key.toLowerCase()))
    )
}

function blockEditingKeys(event: React.KeyboardEvent): void {
    if (!isReadingKey(event)) {
        blockEditing(event)
    }
}

function blockNativeInput(event: Event): void {
    event.preventDefault()
}

// A disabled <fieldset> would also disable collapse headers, and viewers need those to read nested settings.
// Some step controls call APIs directly, so events are blocked here and not only in workflowLogic.
// Text fields keep pointer events for text selection, so mouse-driven edits (cut, context menu) are blocked too.
export function ViewOnlyArea({ children }: { children: React.ReactNode }): JSX.Element {
    const { isViewOnly } = useValues(workflowLogic)
    const areaRef = useRef<HTMLDivElement>(null)

    // React's onBeforeInput is a polyfill that misses deletions and undo, so the native event is used.
    useEffect(() => {
        const area = areaRef.current
        if (!isViewOnly || !area) {
            return
        }
        area.addEventListener('beforeinput', blockNativeInput, true)
        return () => area.removeEventListener('beforeinput', blockNativeInput, true)
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
