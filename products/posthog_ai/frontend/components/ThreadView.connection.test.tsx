import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import api from 'lib/api'
import { projectLogic } from 'scenes/projectLogic'

import { initKeaTests } from '~/test/init'

import { tasksRunsRetrieve } from 'products/tasks/frontend/generated/api'
import type { TaskRunDetailDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import { runStreamLogic } from '../logics/runStreamLogic'
import type { StoredLogEntry } from '../types/wireTypes'
import { ThreadView } from './ThreadView'

jest.mock('products/tasks/frontend/generated/api', () => ({ tasksRunsRetrieve: jest.fn() }))

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
                    <ThreadView virtualized={false} showContextUsage />
                </BindLogic>
            </Provider>
        )
    })

    afterEach(() => {
        cleanup()
        logic?.unmount()
        jest.restoreAllMocks()
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

    it('retries a failed history read from the footer and guards repeated clicks', async () => {
        projectLogic.mount()
        projectLogic.actions.loadCurrentProjectSuccess({ id: 997 } as any)
        jest.mocked(tasksRunsRetrieve).mockResolvedValue({ status: 'completed' } as TaskRunDetailDTOApi)
        const history = jest.spyOn(api.tasks.runs, 'getLogEntries').mockRejectedValueOnce({ status: 403 })
        act(() => logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' }))
        const retry = await screen.findByRole('button', { name: 'Retry' })
        let finishHistory!: (entries: StoredLogEntry[]) => void
        history.mockImplementation(
            () =>
                new Promise((resolve) => {
                    finishHistory = resolve
                })
        )
        act(() => {
            fireEvent.click(retry)
            fireEvent.click(retry)
        })
        await waitFor(() => expect(history).toHaveBeenCalledTimes(2))
        expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull()
        await act(async () =>
            finishHistory([
                notification('session/update', {
                    update: { sessionUpdate: 'agent_message', content: { text: 'Recovered output' } },
                }),
            ])
        )
        await waitFor(() => expect(screen.getByText('Recovered output')).toBeVisible())
        expect(screen.queryByText('Connection lost')).toBeNull()
    })

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

    it('hides context usage and cost during an optimistic resume and restores them on failure', async () => {
        act(() => {
            logic.actions.ingestAcpFrame(
                notification('_posthog/progress', {
                    group: 'setup:previous-run',
                    step: 'agent',
                    status: 'completed',
                    label: 'Started agent',
                }),
                'replay'
            )
            logic.actions.setContextUsage({ used: 12000, size: 1000000, cost: 0.04 })
            logic.actions.handleTerminalStatus({ status: 'completed', replayedFromHistory: true })
        })
        await waitFor(() => expect(screen.getByTestId('max-sandbox-context-usage')).toBeVisible())

        act(() => logic.actions.startOptimisticResume('Continue'))
        await waitFor(() => expect(screen.queryByTestId('max-sandbox-context-usage')).toBeNull())
        expect(screen.getByText('Setting up sandbox')).toBeVisible()

        act(() => logic.actions.rollbackOptimisticResume())
        await waitFor(() => expect(screen.getByTestId('max-sandbox-context-usage')).toBeVisible())
        expect(screen.getByTestId('max-sandbox-context-usage')).toHaveTextContent('Context 1% · $0.04')
    })

    it('uses the startup activity as the state indicator and keeps completed steps expandable', async () => {
        act(() => logic.actions.sseOpened())
        await waitFor(() => expect(screen.getByText('Setting up sandbox')).toBeVisible())

        act(() => {
            logic.actions.ingestAcpFrame(
                notification('_posthog/progress', {
                    group: 'setup:run-1',
                    step: 'sandbox',
                    status: 'in_progress',
                    label: 'Restoring sandbox',
                })
            )
        })
        await waitFor(() => expect(screen.getByText('Restoring sandbox')).toBeVisible())
        expect(screen.queryByText('Setting up sandbox')).toBeNull()

        act(() => {
            logic.actions.ingestAcpFrame(
                notification('_posthog/progress', {
                    group: 'setup:run-1',
                    step: 'sandbox',
                    status: 'completed',
                    label: 'Restored sandbox',
                })
            )
            logic.actions.ingestAcpFrame(
                notification('_posthog/progress', {
                    group: 'setup:run-1',
                    step: 'agent',
                    status: 'in_progress',
                    label: 'Starting agent',
                })
            )
        })
        await waitFor(() => expect(screen.getByText('Starting agent', { exact: true })).toBeVisible())
        expect(screen.getByLabelText('Expand history')).toHaveAttribute('aria-expanded', 'false')
        expect(screen.queryByText('Setting up sandbox')).toBeNull()

        act(() => {
            logic.actions.ingestAcpFrame(
                notification('_posthog/progress', {
                    group: 'setup:run-1',
                    step: 'agent',
                    status: 'completed',
                    label: 'Started agent',
                })
            )
        })
        await waitFor(() => expect(screen.getByLabelText('Expand history')).toHaveAttribute('aria-expanded', 'false'))
        expect(screen.getByText('Started agent')).toBeVisible()
        expect(screen.queryByText('Setting up sandbox')).toBeNull()

        act(() => logic.actions.ingestAcpFrame(notification('_posthog/run_started', {})))
        await waitFor(() => expect(screen.queryByText('Setting up sandbox')).toBeNull())
        fireEvent.click(screen.getByLabelText('Expand history'))
        expect(screen.getByText('Restored sandbox')).toBeVisible()
        expect(screen.getAllByText('Started agent')).toHaveLength(2)
    })
})
