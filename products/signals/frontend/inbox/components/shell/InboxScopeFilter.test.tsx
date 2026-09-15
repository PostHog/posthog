import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import type { InboxPerson } from './InboxPeoplePicker'
import { InboxScopeFilter } from './InboxScopeFilter'

jest.mock('posthog-js')
// The real picker pulls in a popover and avatars. This stand-in lists the roster rows as plain text,
// which is all these tests read from it.
jest.mock('./InboxPeoplePicker', () => ({
    InboxPeoplePicker: ({ people }: { people: InboxPerson[] }) => (
        <ul>
            {people.map((person) => (
                <li key={person.uuid}>
                    {person.name} {person.trailing}
                </li>
            ))}
        </ul>
    ),
}))

describe('InboxScopeFilter', () => {
    beforeEach(() => {
        ;(posthog.capture as jest.Mock).mockClear()
        // Roster holds one teammate; the backend returns a flat `{ uuid: { name, email } }` map.
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/available_reviewers': {
                    'uuid-ada': { name: 'Ada', email: 'ada@example.com' },
                    [MOCK_DEFAULT_USER.uuid]: { name: MOCK_DEFAULT_USER.first_name, email: MOCK_DEFAULT_USER.email },
                },
            },
        })
        initKeaTests()
    })

    afterEach(cleanup)

    // The trigger's accessible name must carry the scope. If the LemonButton tooltip leaks into
    // aria-label instead, a screen reader hears the help sentence and never the active scope.
    it('names the active scope for assistive tech instead of the help tooltip', () => {
        inboxFiltersLogic.mount()
        render(<InboxScopeFilter />)

        expect(screen.getByLabelText('Report scope: For you')).toBeInTheDocument()
    })

    // Scoping to a teammate the roster hasn't loaded (search-filtered, or past the 100-row cap) must
    // not leave the previous teammate's name on the trigger — the data underneath is already the new
    // teammate's, so a stale name misreports whose reports are shown.
    it('drops the cached label when the scope moves to an off-roster teammate', async () => {
        inboxFiltersLogic.mount()
        render(<InboxScopeFilter />)

        inboxFiltersLogic.actions.setScope('teammate:uuid-ada')
        await waitFor(() => expect(screen.getByLabelText('Report scope: Ada')).toBeInTheDocument())

        inboxFiltersLogic.actions.setScope('teammate:uuid-off-roster')
        await waitFor(() => expect(screen.getByLabelText('Report scope: Teammate')).toBeInTheDocument())
        expect(screen.queryByLabelText('Report scope: Ada')).toBeNull()
    })

    // "For you" resolves to whoever opens the link, so a URL that opens to *your* reports for a
    // teammate can only come from your own roster row. Hiding that row as a duplicate of "For you"
    // makes your view the one scope nobody can share.
    it('keeps the signed-in user in the roster so their scope can be shared by URL', async () => {
        inboxFiltersLogic.mount()
        render(<InboxScopeFilter />)

        await waitFor(() => expect(screen.getByText(`${MOCK_DEFAULT_USER.first_name} (you)`)).toBeInTheDocument())
    })
})
