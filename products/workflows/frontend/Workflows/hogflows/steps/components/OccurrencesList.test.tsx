import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { OccurrencesList } from './OccurrencesList'

// Fixed dates far in the future so they're always "future" relative to now
const DATES = {
    apr1: new Date(Date.UTC(2036, 3, 1, 9, 0, 0)),
    apr2: new Date(Date.UTC(2036, 3, 2, 9, 0, 0)),
    apr3: new Date(Date.UTC(2036, 3, 3, 9, 0, 0)),
    past1: new Date(Date.UTC(2020, 0, 1, 9, 0, 0)),
    past2: new Date(Date.UTC(2020, 0, 2, 9, 0, 0)),
}

describe('OccurrencesList', () => {
    afterEach(cleanup)

    it('shows "No upcoming occurrences" when all dates are in the past', () => {
        render(<OccurrencesList occurrences={[DATES.past1, DATES.past2]} isFinite={true} />)
        expect(screen.getByText('No upcoming occurrences')).toBeInTheDocument()
    })

    it('shows "No upcoming occurrences" when occurrences array is empty', () => {
        render(<OccurrencesList occurrences={[]} isFinite={true} />)
        expect(screen.getByText('No upcoming occurrences')).toBeInTheDocument()
    })

    it('renders future occurrences with formatted dates', () => {
        render(<OccurrencesList occurrences={[DATES.apr1, DATES.apr2]} isFinite={true} />)
        expect(screen.getByText('Tuesday, April 1 2036 · 9:00 AM')).toBeInTheDocument()
        expect(screen.getByText('Wednesday, April 2 2036 · 9:00 AM')).toBeInTheDocument()
    })

    it('gives the first occurrence a "next" tag', () => {
        render(<OccurrencesList occurrences={[DATES.apr1, DATES.apr2]} isFinite={true} />)
        expect(screen.getByText('next')).toBeInTheDocument()
    })

    it('gives the last occurrence a "last" tag in a finite list', () => {
        render(<OccurrencesList occurrences={[DATES.apr1, DATES.apr2]} isFinite={true} />)
        expect(screen.getByText('last')).toBeInTheDocument()
    })

    it('collapses long lists showing head + "...N more..." + tail', () => {
        const future = Array.from({ length: 10 }, (_, i) => new Date(Date.UTC(2036, 3, i + 1, 9, 0, 0)))
        render(<OccurrencesList occurrences={future} isFinite={true} />)

        expect(screen.getByText('...5 more occurrences...')).toBeInTheDocument()
        // Head: 4 dates visible
        expect(screen.getByText('Tuesday, April 1 2036 · 9:00 AM')).toBeInTheDocument()
        expect(screen.getByText('Wednesday, April 2 2036 · 9:00 AM')).toBeInTheDocument()
        expect(screen.getByText('Thursday, April 3 2036 · 9:00 AM')).toBeInTheDocument()
        expect(screen.getByText('Friday, April 4 2036 · 9:00 AM')).toBeInTheDocument()
        // Tail: last date visible
        expect(screen.getByText('Thursday, April 10 2036 · 9:00 AM')).toBeInTheDocument()
        // Middle dates should not be rendered
        expect(screen.queryByText('Saturday, April 5 2036 · 9:00 AM')).not.toBeInTheDocument()
    })

    it('shows "...continues indefinitely" for non-finite lists', () => {
        render(<OccurrencesList occurrences={[DATES.apr1, DATES.apr2]} isFinite={false} />)
        expect(screen.getByText('...continues indefinitely')).toBeInTheDocument()
    })

    it('filters out past occurrences and only renders future ones', () => {
        render(<OccurrencesList occurrences={[DATES.past1, DATES.past2, DATES.apr1, DATES.apr2]} isFinite={true} />)
        expect(screen.getByText('Tuesday, April 1 2036 · 9:00 AM')).toBeInTheDocument()
        expect(screen.getByText('Wednesday, April 2 2036 · 9:00 AM')).toBeInTheDocument()
        expect(screen.queryByText('Wednesday, January 1 2020 · 9:00 AM')).not.toBeInTheDocument()
    })
})
