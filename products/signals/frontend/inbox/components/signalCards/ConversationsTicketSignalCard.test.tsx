import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import type { SignalNode } from 'scenes/debug/signals/types'

import { ConversationsTicketSignalCard } from './ConversationsTicketSignalCard'

jest.mock('lib/components/TZLabel', () => ({
    TZLabel: ({ time }: { time: string }) => <span>{time}</span>,
}))

function makeSignal(extra: Record<string, unknown>): SignalNode {
    return {
        signal_id: 'signal-1',
        content: 'The upload progress bar reaches 100% but the file never appears.',
        source_product: 'conversations',
        source_type: 'ticket',
        source_id: '0197-ticket-uuid',
        weight: 1,
        timestamp: '2026-07-13T00:00:00Z',
        extra: extra as unknown as SignalNode['extra'],
    }
}

describe('ConversationsTicketSignalCard', () => {
    afterEach(cleanup)

    it.each([
        ['the ticket number when the emitter stored one', { ticket_number: 4821, channel_source: 'email' }, '4821'],
        ['the ticket uuid for evidence stored without a number', { channel_source: 'email' }, '0197-ticket-uuid'],
    ])('opens the source ticket by %s', (_name, extra, expectedRef) => {
        render(<ConversationsTicketSignalCard signal={makeSignal(extra)} />)

        expect(screen.getByText('Open ticket').closest('a')).toHaveAttribute(
            'href',
            expect.stringContaining(`/support/tickets/${expectedRef}`)
        )
    })

    it('says the source is unavailable instead of linking a ticket it cannot identify', () => {
        const signal = { ...makeSignal({ channel_source: 'email' }), source_id: '' }

        const { container } = render(<ConversationsTicketSignalCard signal={signal} />)

        expect(screen.getByText('Source ticket unavailable')).toBeInTheDocument()
        expect(container.querySelector('a')).toBeNull()
    })
})
