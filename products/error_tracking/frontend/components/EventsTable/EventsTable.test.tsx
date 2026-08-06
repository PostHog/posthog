import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'

import type { ErrorEventType } from 'lib/components/Errors/types'

import { EventsTable } from './EventsTable'

const event = {
    event: '$exception',
    uuid: 'event-1',
    timestamp: '2026-01-01T00:00:00Z',
    distinct_id: 'person-1',
    person: { distinct_ids: ['person-1'], properties: {} },
    properties: {
        $exception_types: ['TypeError'],
        $exception_values: ['Something failed'],
    },
} as ErrorEventType

describe('EventsTable', () => {
    afterEach(() => cleanup())

    it('scrolls the selected event into view after loading', () => {
        const scrollIntoView = jest.fn()
        Element.prototype.scrollIntoView = scrollIntoView
        const props = {
            items: [event],
            hasMore: false,
            selectedEvent: event,
            onEventSelect: jest.fn(),
            onLoadMore: jest.fn(),
        }
        const { rerender } = render(<EventsTable {...props} loading />)

        expect(scrollIntoView).not.toHaveBeenCalled()

        rerender(<EventsTable {...props} loading={false} />)

        expect(scrollIntoView).toHaveBeenCalledWith({ block: 'nearest' })
    })
})
