import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { runStreamLogic } from '../logics/runStreamLogic'
import type { StoredLogEntry } from '../types/wireTypes'
import { ThreadView } from './ThreadView'

// runStreamLogic.test.ts's frame builder isn't exported — copy the one-liner rather than import it.
function notification(method: string, params: Record<string, unknown>): StoredLogEntry {
    return { type: 'notification', notification: { method, params } }
}

describe('ThreadView connection state', () => {
    let logic: ReturnType<typeof runStreamLogic.build>
    const props = { streamKey: 'run-1', conversationId: 'run-1', replayOnly: false }

    beforeEach(() => {
        initKeaTests()
        logic = runStreamLogic(props)
        logic.mount()
        // virtualized={false} so rows render in document flow under jsdom.
        render(
            <Provider>
                <BindLogic logic={runStreamLogic} props={props}>
                    <ThreadView virtualized={false} />
                </BindLogic>
            </Provider>
        )
    })

    afterEach(() => {
        cleanup()
        logic?.unmount()
    })

    // Reconnecting projects runConnectionState → footer RunAlertActivity, and its showConnectionStatus gate
    // must suppress the thinking indicator so a mid-run reconnect doesn't read as normal thinking.
    it('renders the reconnecting banner and suppresses the thinking indicator', async () => {
        logic.actions.sseReconnecting(2)

        await waitFor(() => {
            expect(screen.getByText('Reconnecting to agent')).toBeInTheDocument()
        })
        // maxAttempts flows from the selector (MAX_SSE_RECONNECT_ATTEMPTS = 10), not a hand-passed prop.
        expect(screen.getByText('Attempt 2 of 10')).toBeInTheDocument()
        // Reconnecting drives streamPhase to 'provisioning'; without the gate its "Setting up sandbox" line shows.
        expect(screen.queryByText('Setting up sandbox')).toBeNull()
    })

    // A non-retryable stream error sets sseStatus='error', which the selector projects as connection_failed.
    it('renders the connection-failed banner on a non-retryable stream error', async () => {
        logic.actions.handleStreamError({ errorTitle: 'x', retryable: false })

        await waitFor(() => {
            expect(screen.getByText('Connection lost')).toBeInTheDocument()
        })
    })

    // A folded _posthog/error frame renders inline through ThreadRow's RunAlertActivity swap (agent_error kind).
    it('renders an inline agent-error card for a _posthog/error frame', async () => {
        logic.actions.ingestAcpFrame(notification('_posthog/error', { message: 'boom' }), 'replay')

        await waitFor(() => {
            expect(screen.getByText('Agent error')).toBeInTheDocument()
        })
        expect(screen.getByText('boom')).toBeInTheDocument()
    })

    // A fresh, healthy mount must paint no connection banner.
    it('shows no connection banner on a fresh mount', () => {
        expect(screen.queryByText('Reconnecting to agent')).toBeNull()
        expect(screen.queryByText('Connection lost')).toBeNull()
    })
})
