import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

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

const secondEvent = { ...event, uuid: 'event-2' } as ErrorEventType

describe('EventsTable', () => {
    afterEach(() => cleanup())

    it('scrolls the selected event into view when it first appears', () => {
        const scrollIntoView = jest.fn()
        Element.prototype.scrollIntoView = scrollIntoView

        render(
            <EventsTable
                items={[event]}
                hasMore={false}
                loading={false}
                selectedEvent={event}
                onEventSelect={jest.fn()}
                onLoadMore={jest.fn()}
            />
        )

        expect(scrollIntoView).toHaveBeenCalledWith({ block: 'nearest' })
    })

    it('does not re-scroll when a pagination request toggles loading for the same selection', () => {
        const scrollIntoView = jest.fn()
        Element.prototype.scrollIntoView = scrollIntoView
        const props = {
            items: [event],
            hasMore: true,
            selectedEvent: event,
            onEventSelect: jest.fn(),
            onLoadMore: jest.fn(),
        }
        const { rerender } = render(<EventsTable {...props} loading={false} />)
        scrollIntoView.mockClear()

        // Loading a further page flips loading true then false while the selection is unchanged.
        rerender(<EventsTable {...props} loading />)
        rerender(<EventsTable {...props} loading={false} />)

        expect(scrollIntoView).not.toHaveBeenCalled()
    })

    it.each([
        [
            'reads the derived exception arrays when present',
            { $exception_types: ['TypeError'], $exception_values: ['Something failed'] },
            'TypeError',
            'Something failed',
        ],
        [
            'falls back to the exception list when the derived arrays are absent',
            { $exception_list: [{ type: 'ValueError', value: 'Widget not found' }] },
            'ValueError',
            'Widget not found',
        ],
        [
            'falls back to the exception list when the derived arrays are empty',
            { $exception_types: [], $exception_values: [], $exception_list: [{ type: 'Error', value: 'Boom' }] },
            'Error',
            'Boom',
        ],
        [
            'falls back to the legacy singular properties when there is no exception list',
            { $exception_type: 'SyntaxError', $exception_message: 'Unexpected token' },
            'SyntaxError',
            'Unexpected token',
        ],
        ['labels the row when nothing is available', {}, 'Unknown', 'No message'],
        [
            'stringifies a non-string exception value',
            { $exception_types: ['TypeError'], $exception_values: [{}] },
            'TypeError',
            '{}',
        ],
    ])('%s', (_name, properties, expectedType, expectedValue) => {
        const record = { ...event, properties } as ErrorEventType

        render(
            <EventsTable
                items={[record]}
                hasMore={false}
                loading={false}
                selectedEvent={null}
                onEventSelect={jest.fn()}
                onLoadMore={jest.fn()}
            />
        )

        expect(screen.getByText(expectedType)).toBeInTheDocument()
        expect(screen.getByText(expectedValue)).toBeInTheDocument()
    })

    it('scrolls to the newly selected event when the selection changes', () => {
        const scrollIntoView = jest.fn()
        Element.prototype.scrollIntoView = scrollIntoView
        const props = {
            items: [event, secondEvent],
            hasMore: false,
            loading: false,
            onEventSelect: jest.fn(),
            onLoadMore: jest.fn(),
        }
        const { rerender } = render(<EventsTable {...props} selectedEvent={event} />)
        scrollIntoView.mockClear()

        rerender(<EventsTable {...props} selectedEvent={secondEvent} />)

        expect(scrollIntoView).toHaveBeenCalledWith({ block: 'nearest' })
    })
})
