import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'

import { TransactionalEmailClickTimeline } from './TransactionalEmailClickTimeline'

const RETRY = '[data-attr="transactional-email-outcome-retry"]'

describe('TransactionalEmailClickTimeline', () => {
    it('tells a reader without access what they need, with no retry', () => {
        const { container } = render(
            <TransactionalEmailClickTimeline rows={null} failed denied onRetry={jest.fn()} clickTracking />
        )

        expect(screen.getByText(/You need access to persons and to querying events/)).toBeInTheDocument()
        expect(container.querySelector(RETRY)).toBeNull()
        expect(screen.queryByText('Try again')).toBeNull()
    })

    it('retries clicks that failed to load', () => {
        const onRetry = jest.fn()
        const { container } = render(
            <TransactionalEmailClickTimeline rows={null} failed denied={false} onRetry={onRetry} clickTracking />
        )

        fireEvent.click(container.querySelector(RETRY) as HTMLElement)

        expect(onRetry).toHaveBeenCalledTimes(1)
    })
})
