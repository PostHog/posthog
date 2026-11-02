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

        const others = [
            { id: 'wf-a', name: 'September newsletter', status: 'draft' as const },
            { id: 'wf-b', name: '', status: 'active' as const },
        ]

        it.each([
            { offered: [], button: 'Create broadcast', choice: 'broadcast' },
            { offered: [], button: 'Keep as workflow', choice: 'workflow' },
            { offered: [], button: null, choice: null },
            { offered: others, button: 'Create and move 2 more', choice: 'broadcast_and_move' },
            { offered: others, button: 'Create broadcast', choice: 'broadcast' },
            { offered: others, button: 'Keep as workflow', choice: 'workflow' },
        ])('with $offered.length other workflows, $button resolves to $choice', async ({ offered, button, choice }) => {
            const result = confirmCreateAsBroadcast(offered)
            await screen.findByText(TITLE)
            for (const name of offered.length
                ? ['Also move these 2 workflows to broadcasts?', 'September newsletter', 'Untitled workflow']
                : []) {
                expect(screen.getByText(name)).toBeInTheDocument()
            }

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
