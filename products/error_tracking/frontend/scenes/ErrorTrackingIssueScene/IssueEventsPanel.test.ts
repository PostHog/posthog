import type { ErrorEventType } from 'lib/components/Errors/types'

import { getListSelection } from './IssueEventsPanel'

const events = [{ uuid: 'event-1' }, { uuid: 'event-2' }] as ErrorEventType[]

describe('getListSelection', () => {
    it.each([
        // A selection present on the loaded page is always kept, regardless of pagination.
        { selectedEvent: events[1], canLoadMore: false, queryChanged: false, expected: events[1] },
        { selectedEvent: events[1], canLoadMore: true, queryChanged: false, expected: events[1] },
        // A selection absent from a fully loaded list falls back to the newest event.
        {
            selectedEvent: { uuid: 'missing' } as ErrorEventType,
            canLoadMore: false,
            queryChanged: false,
            expected: events[0],
        },
        // A filter change proves the old selection belongs to a different result set.
        {
            selectedEvent: { uuid: 'missing' } as ErrorEventType,
            canLoadMore: true,
            queryChanged: true,
            expected: events[0],
        },
        // No selection always falls back to the newest event.
        { selectedEvent: null, canLoadMore: false, queryChanged: false, expected: events[0] },
        { selectedEvent: null, canLoadMore: true, queryChanged: false, expected: events[0] },
    ])(
        'reconciles the current selection with the loaded list',
        ({ selectedEvent, canLoadMore, queryChanged, expected }) => {
            expect(getListSelection(events, selectedEvent, canLoadMore, queryChanged)).toBe(expected)
        }
    )

    it('keeps a selection missing from the loaded page while more pages can load', () => {
        // A timestamp-linked exception can live past the first page; reconciling it to the newest
        // event here would rewrite the URL and lose the linked exception the user opened.
        const linkedEvent = { uuid: 'missing' } as ErrorEventType
        expect(getListSelection(events, linkedEvent, true, false)).toBe(linkedEvent)
    })

    it('closes the selection for an empty list', () => {
        expect(getListSelection([], events[0], false, false)).toBeNull()
    })
})
