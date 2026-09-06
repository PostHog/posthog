import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { RunAlertActivity } from './RunAlertActivity'

describe('RunAlertActivity', () => {
    afterEach(cleanup)

    it('shows the reconnect attempt counter while reconnecting', () => {
        render(<RunAlertActivity kind="reconnecting" attempt={2} maxAttempts={10} />)

        expect(screen.getByText('Reconnecting to agent')).toBeInTheDocument()
        expect(screen.getByText('Attempt 2 of 10')).toBeInTheDocument()
    })

    it.each([
        ['connection_failed', 'Connection lost'],
        ['agent_error', 'Agent error'],
        ['agent_crash', 'Agent stopped unexpectedly'],
    ] as const)('renders the %s title with its detail message', (kind, title) => {
        render(<RunAlertActivity kind={kind} message="boom" />)

        expect(screen.getByText(title)).toBeInTheDocument()
        expect(screen.getByText('boom')).toBeInTheDocument()
    })

    it('offers an in-place retry when onRetry is set', () => {
        const onRetry = jest.fn()
        render(<RunAlertActivity kind="connection_failed" message="boom" onRetry={onRetry} />)

        const retry = screen.getByText('Retry')
        fireEvent.click(retry)
        expect(onRetry).toHaveBeenCalledTimes(1)
    })

    it('shows no retry button without onRetry', () => {
        render(<RunAlertActivity kind="connection_failed" message="boom" />)
        expect(screen.queryByText('Retry')).not.toBeInTheDocument()
    })
})
