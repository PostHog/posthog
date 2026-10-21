import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { useForegroundStream } from '../../../hooks/useForegroundStream'
import type { ActiveCreation } from '../../../logics/runnerPanelLogic'
import { SidePanelRunnerImpl } from './SidePanelRunnerImpl'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    BindLogic: ({ children }: { children: React.ReactNode }) => children,
    useActions: jest.fn(),
    useValues: jest.fn(),
}))

jest.mock('../taskTrackerSceneLogic', () => ({ taskTrackerSceneLogic: jest.fn(() => ({ __mock: 'scene' })) }))
jest.mock('../../../hooks/useForegroundStream', () => ({ useForegroundStream: jest.fn() }))
jest.mock('../../../hooks/useAttachedContext', () => ({ useAttachedContext: jest.fn() }))
jest.mock('./TaskComposer', () => ({ TaskComposer: () => <div data-attr="task-composer" /> }))
jest.mock('./TaskRunChat', () => ({ TaskRunChat: () => <div data-attr="task-run-chat" /> }))
jest.mock('./StartupRunChat', () => ({ StartupRunChat: () => <div data-attr="startup-run-chat" /> }))
jest.mock('./TaskHistory', () => ({
    TaskHistoryPanel: () => <div data-attr="task-history-list" />,
    TaskHistoryPreview: () => <div data-attr="task-history-preview" />,
}))

describe('SidePanelRunnerImpl', () => {
    beforeEach(() => {
        ;(useActions as jest.Mock).mockReturnValue({
            toggleHistory: jest.fn(),
            updateActiveCreationRun: jest.fn(),
            setStartupDraft: jest.fn(),
        })
    })

    afterEach(() => {
        cleanup()
        jest.clearAllMocks()
    })

    function setValues(activeCreation: ActiveCreation | null, historyExpanded: boolean): void {
        ;(useValues as jest.Mock).mockReturnValue({ activeCreation, historyExpanded })
    }

    it('keeps a host composer on screen when the shared panel left history expanded', () => {
        // The report panel supplies its own composer and offers no way into the history list, so an
        // expanded history from the PostHog AI panel must not take the composer's place.
        setValues(null, true)

        render(<SidePanelRunnerImpl panelId="panel" composer={<div data-attr="host-composer" />} />)

        expect(screen.getByTestId('host-composer')).toBeInTheDocument()
        expect(screen.queryByTestId('task-history-list')).not.toBeInTheDocument()
    })

    it('still shows history for a host that has no composer of its own', () => {
        setValues(null, true)

        render(<SidePanelRunnerImpl panelId="panel" />)

        expect(screen.getByTestId('task-history-list')).toBeInTheDocument()
    })

    it.each([
        { name: 'a startup stream', creation: { streamKey: 'draft-1' }, registered: 'draft-1' },
        {
            name: 'a run, which TaskRunChat registers',
            creation: { streamKey: 'run-b', taskId: 'task-1', runId: 'run-b' },
            registered: null,
        },
    ])('registers the foreground stream for $name', ({ creation, registered }) => {
        setValues(creation as ActiveCreation, false)

        render(<SidePanelRunnerImpl panelId="panel" />)

        expect(useForegroundStream).toHaveBeenLastCalledWith(registered)
    })
})
