import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'

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

    it('shows the clicks once a retry loads them', () => {
        function RetryingCard(): JSX.Element {
            const [failed, setFailed] = useState(true)
            return (
                <TransactionalEmailClickTimeline
                    rows={failed ? null : []}
                    failed={failed}
                    denied={false}
                    onRetry={() => setFailed(false)}
                    clickTracking
                />
            )
        }
        const { container } = render(<RetryingCard />)

        fireEvent.click(container.querySelector(RETRY) as HTMLElement)

        expect(container.querySelector(RETRY)).toBeNull()
        expect(screen.getByText(/No clicks yet/)).toBeInTheDocument()
    })
})
