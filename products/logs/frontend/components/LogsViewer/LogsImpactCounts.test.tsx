import '@testing-library/jest-dom'

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'

import { initKeaTests } from '~/test/init'

import type { _LogsImpactResponseApi } from 'products/logs/frontend/generated/api.schemas'

import { LogsImpactCounts } from './LogsImpactCounts'

describe('LogsImpactCounts', () => {
    beforeEach(() => {
        initKeaTests()
    })

    const impact: _LogsImpactResponseApi = {
        total: 100,
        logsWithSessionId: 90,
        sessions: 3,
        logsWithDistinctId: 0,
        users: 0,
        topSessions: [],
        topUsers: [],
        sessionGroupKey: { source: 'log', key: 'sessionId' },
        personGroupKey: null,
    }

    it('closes the sessions drill-down when the session player modal opens', async () => {
        render(<LogsImpactCounts impact={impact} />)

        fireEvent.click(screen.getByText('sessions'))
        expect(screen.getByText(/Estimated unique session IDs/)).toBeInTheDocument()

        // The player modal renders below the popover layer, so the drill-down must close.
        act(() => {
            sessionPlayerModalLogic.actions.openSessionPlayer({ id: 'some-session-id' })
        })
        // The popover stays in the DOM until its exit transition completes.
        await waitFor(() => {
            expect(screen.queryByText(/Estimated unique session IDs/)).not.toBeInTheDocument()
        })

        // The drill-down stays closed after the modal closes; it must not pop back open.
        act(() => {
            sessionPlayerModalLogic.actions.closeSessionPlayer()
        })
        expect(screen.queryByText(/Estimated unique session IDs/)).not.toBeInTheDocument()
    })
})
