import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ScoutRunNowButton } from './ScoutRunNowButton'

jest.mock('lib/utils/accessControlUtils', () => ({
    ...jest.requireActual('lib/utils/accessControlUtils'),
    getAccessControlDisabledReason: jest.fn(() => null),
}))

const mockGetAccessControlDisabledReason = getAccessControlDisabledReason as jest.MockedFunction<
    typeof getAccessControlDisabledReason
>

describe('ScoutRunNowButton', () => {
    let dispatchedBodies: unknown[]

    beforeEach(() => {
        dispatchedBodies = []
        mockGetAccessControlDisabledReason.mockReturnValue(null)
        useMocks({
            get: {
                '/api/projects/:team/signals/scout/configs/': [],
            },
            post: {
                '/api/projects/:team/signals/scout/configs/:id/run/': async ({ request }) => {
                    dispatchedBodies.push(await request.json().catch(() => null))
                    return [202, { skill_name: 'signals-scout-foo', workflow_id: 'wf-1', started: true }]
                },
            },
        })
        initKeaTests()
    })

    afterEach(cleanup)

    it('dispatches with no steering from the button itself', async () => {
        const { getByText } = render(<ScoutRunNowButton configId="config-1" />)

        fireEvent.click(getByText('Run now'))

        // No body at all, so the request carries no note for the endpoint to gate on.
        await waitFor(() => expect(dispatchedBodies).toEqual([null]))
    })

    // The note is the whole point of the side action, and it is trimmed so whitespace around a
    // pasted note never reads as steering.
    it('dispatches the trimmed note from the side action', async () => {
        const { container, findByText, getByPlaceholderText, getAllByText } = render(
            <ScoutRunNowButton configId="config-1" />
        )

        fireEvent.click(container.querySelector('[data-attr="scout-run-now-with-note"]')!)
        await findByText('Run with a note')
        fireEvent.change(getByPlaceholderText(/focus on the checkout regression/), {
            target: { value: '  look at checkout  ' },
        })
        // The dialog's own button carries the same label as the trigger, and it renders last.
        fireEvent.click(getAllByText('Run now').at(-1)!)

        await waitFor(() => expect(dispatchedBodies).toEqual([{ note: 'look at checkout' }]))
    })

    // A member an admin restricted from skill editing must not steer a run through a note instead —
    // the note reaches the agent verbatim. The plain run stays open to them.
    it('disables only the note path without skill editor access', () => {
        mockGetAccessControlDisabledReason.mockReturnValue('No access')
        const { container } = render(<ScoutRunNowButton configId="config-1" />)

        expect(container.querySelector('[data-attr="scout-run-now-with-note"]')?.getAttribute('aria-disabled')).toBe(
            'true'
        )
        expect(container.querySelector('[data-attr="scout-run-now"]')?.getAttribute('aria-disabled')).toBe('false')
    })
})
