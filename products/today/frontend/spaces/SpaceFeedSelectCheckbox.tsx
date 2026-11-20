import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { Checkbox, cn } from '@posthog/quill'

import { spaceFeedSelectionLogic } from './spaceFeedSelectionLogic'

interface SpaceFeedSelectCheckboxProps {
    spaceId: string
    sessionId: string
    title: string
    /** The row's status icon, which the checkbox takes the place of. */
    children: ReactNode
    className?: string
}

/**
 * The row's status icon, which turns into a checkbox on hover or focus, and on every row while anything is
 * selected. Shift-click picks a range.
 */
export function SpaceFeedSelectCheckbox({
    spaceId,
    sessionId,
    title,
    children,
    className,
}: SpaceFeedSelectCheckboxProps): JSX.Element {
    const { selectedSessionIds } = useValues(spaceFeedSelectionLogic({ id: spaceId }))
    const { toggleSessionSelection, selectSessionRange } = useActions(spaceFeedSelectionLogic({ id: spaceId }))
    const selecting = selectedSessionIds.length > 0
    const revealed =
        'group-focus-within/card:opacity-100 group-focus-within/row:opacity-100 group-hover/card:opacity-100 group-hover/row:opacity-100'
    const concealed =
        'group-focus-within/card:opacity-0 group-focus-within/row:opacity-0 group-hover/card:opacity-0 group-hover/row:opacity-0'

    return (
        <span className={cn('relative flex size-3.5 shrink-0 items-center justify-center', className)}>
            <span
                className={cn(
                    'flex transition-opacity motion-reduce:transition-none',
                    selecting ? 'opacity-0' : concealed
                )}
            >
                {children}
            </span>
            <Checkbox
                size="sm"
                checked={selectedSessionIds.includes(sessionId)}
                onCheckedChange={(_, { event }) => {
                    if (event instanceof MouseEvent && event.shiftKey) {
                        selectSessionRange(sessionId)
                    } else {
                        toggleSessionSelection(sessionId)
                    }
                }}
                onClick={(event) => event.stopPropagation()}
                aria-label={`Select ${title}`}
                // Above the row link's overlay, so a click picks the session instead of opening it.
                className={cn(
                    'absolute z-1 transition-opacity motion-reduce:transition-none',
                    !selecting && cn('opacity-0', revealed)
                )}
                data-attr="today-space-feed-select"
            />
        </span>
    )
}
