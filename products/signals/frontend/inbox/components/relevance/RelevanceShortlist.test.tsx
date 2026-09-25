import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'

import { RelevanceShortlist } from './RelevanceShortlist'

const props = {
    reports: [],
    loading: false,
    failed: false,
    saving: false,
    lastSnoozed: null,
    onRetry: jest.fn(),
    onShowQueue: jest.fn(),
    onSnooze: jest.fn(),
}

describe('Relevance shortlist', () => {
    it('keeps the full queue available when the shortlist fails', () => {
        render(<RelevanceShortlist {...props} failed />)
        expect(screen.queryByText(/Nothing needs/)).not.toBeInTheDocument()
        fireEvent.click(screen.getAllByText('Try again')[0])
        expect(props.onRetry).toHaveBeenCalled()
        fireEvent.click(screen.getByText('Browse all reports'))
        expect(props.onShowQueue).toHaveBeenCalled()
    })
    it('does not claim the inbox is empty while loading', () => {
        render(<RelevanceShortlist {...props} loading />)
        expect(screen.queryByText(/Nothing needs/)).not.toBeInTheDocument()
    })
})
