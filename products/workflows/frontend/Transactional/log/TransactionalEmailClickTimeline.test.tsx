import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'

import { TransactionalEmailClickTimeline } from './TransactionalEmailClickTimeline'

describe('TransactionalEmailClickTimeline', () => {
    it('tells a reader without access what they need, with no retry', () => {
        render(<TransactionalEmailClickTimeline rows={null} failed denied onRetry={jest.fn()} clickTracking />)

        expect(screen.getByText(/You need access to persons and to querying events/)).toBeInTheDocument()
        expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
    })

    it('retries clicks that failed to load', () => {
        const onRetry = jest.fn()
        render(<TransactionalEmailClickTimeline rows={null} failed denied={false} onRetry={onRetry} clickTracking />)

        fireEvent.click(screen.getAllByRole('button', { name: 'Try again' })[0])

        expect(onRetry).toHaveBeenCalledTimes(1)
    })
})
