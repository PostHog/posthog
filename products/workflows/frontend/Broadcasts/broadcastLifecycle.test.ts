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
        const escape = (): boolean =>
            fireEvent.keyDown(screen.getByText(TITLE).closest('.ReactModal__Content')!, { key: 'Escape', keyCode: 27 })

        it.each([
            { otherCount: 0, button: 'Create broadcast', choice: 'broadcast' },
            { otherCount: 0, button: 'Keep as workflow', choice: 'workflow' },
            { otherCount: 0, button: null, choice: null },
            { otherCount: 2, button: 'Create and move 2 more', choice: 'broadcast_and_move' },
            { otherCount: 2, button: 'Create broadcast', choice: 'broadcast' },
            { otherCount: 2, button: 'Keep as workflow', choice: 'workflow' },
        ])('with $otherCount other workflows, $button resolves to $choice', async ({ otherCount, button, choice }) => {
            const result = confirmCreateAsBroadcast(otherCount)
            await screen.findByText(TITLE)

            if (button) {
                fireEvent.click(screen.getByText(button))
            } else {
                escape()
            }

            await expect(result).resolves.toBe(choice)
            await waitFor(() => expect(screen.queryByText(TITLE)).not.toBeInTheDocument())
        })
    })
})
