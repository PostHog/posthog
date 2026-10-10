import type { MouseEvent } from 'react'

import { IconCopy, IconFilter, IconPencil, IconPlus, IconTrash, IconUndo } from '@posthog/icons'
import { Button } from '@posthog/quill'

export interface SentenceEventActionsProps {
    /** Null hides the action. A filter on one event only matters once there are several events. */
    onFilter: (() => void) | null
    onRename: () => void
    onDuplicate: () => void
    onCombine: () => void
    /** Null unless the events are counted together. */
    onSplitApart: (() => void) | null
    /** Null when this is the only event. */
    onRemove: (() => void) | null
}

// The buttons sit inside the event picker, and a press must not take the focus from its search field.
function keepFocus(event: MouseEvent): void {
    event.preventDefault()
}

/** What can be done to the event the picker was opened from, apart from changing it. */
export function SentenceEventActions({
    onFilter,
    onRename,
    onDuplicate,
    onCombine,
    onSplitApart,
    onRemove,
}: SentenceEventActionsProps): JSX.Element {
    return (
        <div className="flex flex-wrap gap-1">
            {onFilter && (
                <Button
                    size="sm"
                    onMouseDown={keepFocus}
                    onClick={onFilter}
                    data-attr="quill-insight-event-action-filter"
                >
                    <IconFilter />
                    Filter this event
                </Button>
            )}
            <Button size="sm" onMouseDown={keepFocus} onClick={onRename} data-attr="quill-insight-event-action-rename">
                <IconPencil />
                Rename
            </Button>
            <Button
                size="sm"
                onMouseDown={keepFocus}
                onClick={onDuplicate}
                data-attr="quill-insight-event-action-duplicate"
            >
                <IconCopy />
                Duplicate
            </Button>
            <Button
                size="sm"
                onMouseDown={keepFocus}
                onClick={onCombine}
                data-attr="quill-insight-event-action-combine"
            >
                <IconPlus />
                Count together with another event
            </Button>
            {onSplitApart && (
                <Button
                    size="sm"
                    onMouseDown={keepFocus}
                    onClick={onSplitApart}
                    data-attr="quill-insight-event-action-split-apart"
                >
                    <IconUndo />
                    Show as separate lines
                </Button>
            )}
            {onRemove && (
                <Button
                    size="sm"
                    variant="destructive"
                    onMouseDown={keepFocus}
                    onClick={onRemove}
                    data-attr="quill-insight-event-action-remove"
                >
                    <IconTrash />
                    Remove
                </Button>
            )}
        </div>
    )
}
