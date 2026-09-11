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
        ['agent_error', 'Run stopped'],
        ['agent_error_continued', 'Agent error'],
        ['message_undelivered', 'Message not delivered'],
        ['agent_crash', 'Agent stopped unexpectedly'],
    ] as const)('renders the %s title with its detail message', (kind, title) => {
        render(<RunAlertActivity kind={kind} message="boom" />)

        expect(screen.getByText(title)).toBeInTheDocument()
        expect(screen.getByText('boom')).toBeInTheDocument()
    })

    it('notes the undelivered follow-up on a stopped run', () => {
        render(<RunAlertActivity kind="agent_error" message="boom" undeliveredMessage />)

        expect(screen.getByText('Your last message was not delivered.')).toBeInTheDocument()
    })
    it.each([true, false])('only offers Retry for a retryable connection failure: %s', (retryable) => {
        const onRetry = jest.fn()
        render(<RunAlertActivity kind="connection_failed" retryable={retryable} onRetry={onRetry} />)
        const retry = screen.queryByRole('button', { name: 'Retry' })
        expect(retry !== null).toBe(retryable)
        if (retry) {
            fireEvent.click(retry)
        }
        expect(onRetry).toHaveBeenCalledTimes(Number(retryable))
    })
})
