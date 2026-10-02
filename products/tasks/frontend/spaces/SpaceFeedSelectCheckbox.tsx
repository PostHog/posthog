import { useActions, useValues } from 'kea'

import { Checkbox, cn } from '@posthog/quill'

import { spaceFeedSelectionLogic } from './spaceFeedSelectionLogic'

interface SpaceFeedSelectCheckboxProps {
    spaceId: string
    sessionId: string
    title: string
}

/** Picks a session for the feed's bulk actions, like a row checkbox in Gmail. Shift-click picks a range. */
export function SpaceFeedSelectCheckbox({ spaceId, sessionId, title }: SpaceFeedSelectCheckboxProps): JSX.Element {
    const { selectedSessionIds } = useValues(spaceFeedSelectionLogic({ id: spaceId }))
    const { toggleSessionSelection, selectSessionRange } = useActions(spaceFeedSelectionLogic({ id: spaceId }))
    const selecting = selectedSessionIds.length > 0

    return (
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
                'z-1 transition-opacity',
                !selecting &&
                    'opacity-0 group-focus-within/card:opacity-100 group-focus-within/row:opacity-100 group-hover/card:opacity-100 group-hover/row:opacity-100'
            )}
            data-attr="today-space-feed-select"
        />
    )
}
