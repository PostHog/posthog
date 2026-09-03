import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { InboxScopeFilter } from './InboxScopeFilter'

jest.mock('posthog-js')
// The people picker isn't needed to exercise the trigger label, and it pulls in a popover + avatars.
jest.mock('./InboxPeoplePicker', () => ({ InboxPeoplePicker: () => null }))

describe('InboxScopeFilter', () => {
    beforeEach(() => {
        ;(posthog.capture as jest.Mock).mockClear()
        // Roster holds one teammate; the backend returns a flat `{ uuid: { name, email } }` map.
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/available_reviewers': {
                    'uuid-ada': { name: 'Ada', email: 'ada@example.com' },
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
        await waitFor(() => expect(screen.getByText('Ada')).toBeInTheDocument())

        inboxFiltersLogic.actions.setScope('teammate:uuid-off-roster')
        await waitFor(() => expect(screen.getByText('Teammate')).toBeInTheDocument())
        expect(screen.queryByText('Ada')).toBeNull()
    })
})
