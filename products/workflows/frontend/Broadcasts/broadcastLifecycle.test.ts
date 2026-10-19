import '@testing-library/jest-dom'

import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { archiveDisabledReason, confirmCreateAsBroadcast } from './broadcastLifecycle'

describe('broadcastLifecycle', () => {
    describe('archiveDisabledReason', () => {
        it.each([
            { runs: 'runs not loaded yet', statuses: null, blocked: true },
            { runs: 'no runs', statuses: [], blocked: false },
            { runs: 'a finished and a failed run', statuses: ['completed', 'failed'], blocked: false },
            { runs: 'rows whose runs have not loaded', statuses: [undefined], blocked: false },
            { runs: 'a queued run', statuses: ['queued'], blocked: true },
            { runs: 'an older run still sending', statuses: ['completed', 'active'], blocked: true },
        ])('with $runs blocks archiving: $blocked', ({ statuses, blocked }) => {
            expect(!!archiveDisabledReason(statuses)).toBe(blocked)
        })
    })

    describe('confirmCreateAsBroadcast', () => {
        it.each([
            {
                action: 'clicking "Create broadcast"',
                answer: () => userEvent.click(screen.getByText('Create broadcast')),
                choice: 'broadcast',
            },
            {
                action: 'clicking "Keep as workflow"',
                answer: () => userEvent.click(screen.getByText('Keep as workflow')),
                choice: 'workflow',
            },
            { action: 'pressing Escape', answer: () => userEvent.keyboard('{Escape}'), choice: null },
        ])('resolves to $choice after $action', async ({ answer, choice }) => {
            const result = confirmCreateAsBroadcast()
            await screen.findByText('Create this as a broadcast?')

            await answer()

            await expect(result).resolves.toBe(choice)
            await waitFor(() => expect(screen.queryByText('Create this as a broadcast?')).not.toBeInTheDocument())
        })
    })
})
