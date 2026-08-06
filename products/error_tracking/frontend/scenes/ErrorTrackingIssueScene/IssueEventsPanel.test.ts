import type { ErrorEventType } from 'lib/components/Errors/types'

import { getListSelection } from './IssueEventsPanel'

const events = [{ uuid: 'event-1' }, { uuid: 'event-2' }] as ErrorEventType[]

describe('getListSelection', () => {
    it.each([
        { selectedEvent: events[1], expected: events[1] },
        { selectedEvent: { uuid: 'missing' } as ErrorEventType, expected: events[0] },
        { selectedEvent: null, expected: events[0] },
    ])('reconciles the current selection with the loaded list', ({ selectedEvent, expected }) => {
        expect(getListSelection(events, selectedEvent)).toBe(expected)
    })

    it('closes the selection for an empty list', () => {
        expect(getListSelection([], events[0])).toBeNull()
    })
})
