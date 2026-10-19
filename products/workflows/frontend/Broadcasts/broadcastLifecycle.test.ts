import '@testing-library/jest-dom'

import { fireEvent, screen, waitFor } from '@testing-library/react'

import { archiveDisabledReason, confirmCreateAsBroadcast } from './broadcastLifecycle'

const TITLE = 'Track this send as a broadcast?'

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
                answer: () => fireEvent.click(screen.getByText('Create broadcast')),
                choice: 'broadcast',
            },
            {
                action: 'clicking "Keep as workflow"',
                answer: () => fireEvent.click(screen.getByText('Keep as workflow')),
                choice: 'workflow',
            },
            {
                action: 'pressing Escape',
                answer: () =>
                    fireEvent.keyDown(screen.getByText(TITLE).closest('.ReactModal__Content')!, {
                        key: 'Escape',
                        keyCode: 27,
                    }),
                choice: null,
            },
        ])('resolves to $choice after $action', async ({ answer, choice }) => {
            const result = confirmCreateAsBroadcast()
            await screen.findByText(TITLE)

            await answer()

            await expect(result).resolves.toBe(choice)
            await waitFor(() => expect(screen.queryByText(TITLE)).not.toBeInTheDocument())
        })
    })
})
