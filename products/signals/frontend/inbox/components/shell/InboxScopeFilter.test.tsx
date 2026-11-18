import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { InboxScopeFilter } from './InboxScopeFilter'

jest.mock('posthog-js')
jest.mock('lib/components/MemberSelect', () => ({
    MemberSelect: ({
        options,
        children,
        defaultLabel,
        extraOptions = [],
        onChange,
        onSelectOption,
    }: {
        options: { uuid: string; name: string; trailing?: string }[]
        children: () => JSX.Element
        defaultLabel: string
        extraOptions?: { label: string; onClick: () => void }[]
        onChange: () => void
        onSelectOption: (uuid: string, label: string) => void
    }) => (
        <>
            {children()}
            <ul>
                {extraOptions.map((option) => (
                    <li key={option.label}>
                        <button type="button" role="menuitem" onClick={option.onClick}>
                            {option.label}
                        </button>
                    </li>
                ))}
                <li>
                    <button type="button" role="menuitem" onClick={onChange}>
                        {defaultLabel}
                    </button>
                </li>
                {options.map((person) => (
                    <li key={person.uuid}>
                        <button type="button" role="menuitem" onClick={() => onSelectOption(person.uuid, person.name)}>
                            {person.name} {person.trailing}
                        </button>
                    </li>
                ))}
            </ul>
        </>
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

        inboxFiltersLogic.actions.loadAvailableReviewersSuccess([])
        expect(screen.getByLabelText('Report scope: Ada')).toBeInTheDocument()

        inboxFiltersLogic.actions.setScope('teammate:uuid-off-roster')
        await waitFor(() => expect(screen.getByLabelText('Report scope: Teammate')).toBeInTheDocument())
        expect(screen.queryByLabelText('Report scope: Ada')).toBeNull()
    })

    it('uses the signed-in user row to select For you without a duplicate menu item', async () => {
        inboxFiltersLogic.mount()
        render(<InboxScopeFilter />)

        await screen.findByText(`${MOCK_DEFAULT_USER.first_name} (you)`)
        expect(screen.queryByText('For you', { selector: '[role=menuitem]' })).not.toBeInTheDocument()

        fireEvent.click(screen.getByText('Entire project', { selector: '[role=menuitem]' }))
        await waitFor(() => expect(screen.getByLabelText('Report scope: Entire project')).toBeInTheDocument())

        inboxFiltersLogic.actions.loadAvailableReviewersSuccess([])
        await waitFor(() => expect(screen.queryByText('Ada', { selector: '[role=menuitem]' })).not.toBeInTheDocument())
        const fallbackRow = await screen.findByText(`${MOCK_DEFAULT_USER.first_name} (you)`)
        fireEvent.click(fallbackRow)
        await waitFor(() => expect(screen.getByLabelText('Report scope: For you')).toBeInTheDocument())
    })
})
