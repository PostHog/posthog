/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { INBOX_EVENTS } from '../../inboxAnalytics'
import { inboxSceneLogic } from '../../inboxSceneLogic'
import { InboxSetupIncomplete } from './InboxSetupIncomplete'

jest.mock('posthog-js')

function viewedEvents(): unknown[] {
    return (posthog.capture as jest.Mock).mock.calls.filter(([event]) => event === INBOX_EVENTS.SETUP_INCOMPLETE_VIEWED)
}

describe('InboxSetupIncomplete', () => {
    beforeEach(() => {
        ;(posthog.capture as jest.Mock).mockClear()
        useMocks({ get: { '/api/projects/:team_id/signals/reports/available_reviewers': {} } })
        initKeaTests()
        inboxSceneLogic.mount()
    })

    afterEach(cleanup)

    // The list stays mounted behind a panel, so an unguarded mount effect counted a view of a
    // surface the user never saw — inflating the denominator of the recovery rate on its own.
    it('does not record a view while a panel covers the list', async () => {
        act(() => {
            inboxSceneLogic.actions.setScratchpadOpen(true)
        })

        render(<InboxSetupIncomplete />)

        await waitFor(() => expect(screen.getByText("Setup isn't finished")).toBeInTheDocument())
        expect(viewedEvents()).toHaveLength(0)

        act(() => {
            inboxSceneLogic.actions.setScratchpadOpen(false)
        })
        await waitFor(() => expect(viewedEvents()).toHaveLength(1))
    })

    it('records one view when the surface is the visible one', async () => {
        render(<InboxSetupIncomplete />)

        await waitFor(() => expect(viewedEvents()).toHaveLength(1))

        act(() => {
            inboxSceneLogic.actions.setScratchpadOpen(true)
            inboxSceneLogic.actions.setScratchpadOpen(false)
        })
        expect(viewedEvents()).toHaveLength(1)
    })
})
