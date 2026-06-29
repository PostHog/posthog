import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import type { RunStatus } from '../logics/runStreamLogic'
import type { PermissionRequestRecord } from '../types/streamTypes'
// The compound is exercised synchronously from the impl; the public lazy wrapper is covered separately below.
import { RunViewer as LazyRunViewer } from './RunViewer'
import { RunViewer } from './RunViewerImpl'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    BindLogic: ({ children }: { children: React.ReactNode }) => children,
    useActions: jest.fn(),
    useValues: jest.fn(),
}))

jest.mock('../logics/runStreamLogic', () => ({
    runStreamLogic: jest.fn(() => ({ __mock: 'runStreamLogic' })),
    isTerminalRunStatus: (status: string | null) =>
        status != null && ['completed', 'failed', 'cancelled'].includes(status),
}))

jest.mock('./ThreadView', () => ({ ThreadView: () => <div data-attr="thread" /> }))
jest.mock('./ResourcesBar', () => ({ ResourcesBar: () => <div data-attr="resources" /> }))
jest.mock('./ContextUsageBar', () => ({ ContextUsageBar: () => <div data-attr="context" /> }))
jest.mock('./PermissionInput', () => ({ PermissionInput: () => <div data-attr="permission" /> }))
jest.mock('./QuestionInput', () => ({ QuestionInput: () => <div data-attr="question" /> }))

const composerProps = {
    composerValue: '',
    onComposerChange: jest.fn(),
    onComposerSubmit: jest.fn(),
    composerLoading: false,
}

function setValues(
    overrides: Partial<{
        currentRunStatus: RunStatus | null
        pendingPermissionRequest: PermissionRequestRecord | null
        bootstrapLoading: boolean
        threadItems: unknown[]
    }>
): void {
    ;(useValues as jest.Mock).mockReturnValue({
        bootstrapLoading: false,
        threadItems: [],
        pendingPermissionRequest: null,
        currentRunStatus: 'in_progress',
        ...overrides,
    })
}

describe('RunViewer', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        ;(useActions as jest.Mock).mockReturnValue({ bootstrapRun: jest.fn(), reset: jest.fn() })
        setValues({})
    })

    afterEach(() => {
        cleanup()
    })

    const renderLive = (statusOrOverrides: RunStatus | null | Parameters<typeof setValues>[0]): void => {
        if (typeof statusOrOverrides === 'object' && statusOrOverrides !== null) {
            setValues(statusOrOverrides)
        } else {
            setValues({ currentRunStatus: statusOrOverrides as RunStatus | null })
        }
        render(<RunViewer taskId="task-1" runId="run-1" interaction="live" {...composerProps} />)
    }

    it.each<RunStatus>(['queued', 'in_progress'])('shows the composer for an active run (%s)', (status) => {
        renderLive(status)
        expect(screen.getByTestId('composer')).toBeInTheDocument()
    })

    it('does not show the composer during the null bootstrap window', () => {
        renderLive(null)
        expect(screen.queryByTestId('composer')).not.toBeInTheDocument()
        // The thread still renders while bootstrapping.
        expect(screen.getByTestId('thread')).toBeInTheDocument()
    })

    it.each<RunStatus>(['completed', 'failed', 'cancelled'])(
        'shows the composer for a terminal run so a new run can be started (%s)',
        (status) => {
            renderLive(status)
            expect(screen.getByTestId('composer')).toBeInTheDocument()
        }
    )

    it('shows the permission input instead of the composer when a permission request is pending', () => {
        renderLive({
            currentRunStatus: 'in_progress',
            pendingPermissionRequest: { requestId: 'r1' } as PermissionRequestRecord,
        })
        expect(screen.getByTestId('permission')).toBeInTheDocument()
        expect(screen.queryByTestId('composer')).not.toBeInTheDocument()
    })

    it('shows the question input when the pending request carries questions', () => {
        renderLive({
            currentRunStatus: 'in_progress',
            pendingPermissionRequest: { requestId: 'r1', questions: [{ question: 'q' }] } as PermissionRequestRecord,
        })
        expect(screen.getByTestId('question')).toBeInTheDocument()
        expect(screen.queryByTestId('composer')).not.toBeInTheDocument()
    })

    it('does not show a composer in read-only mode even for an active run', () => {
        setValues({ currentRunStatus: 'in_progress' })
        render(<RunViewer taskId="task-1" runId="run-1" interaction="read-only" />)
        expect(screen.queryByTestId('composer')).not.toBeInTheDocument()
        expect(screen.queryByTestId('resources')).not.toBeInTheDocument()
        expect(screen.getByTestId('thread')).toBeInTheDocument()
    })

    it('omits the composer in live mode when no composer props are supplied', () => {
        setValues({ currentRunStatus: 'in_progress' })
        render(<RunViewer taskId="task-1" runId="run-1" interaction="live" />)
        expect(screen.queryByTestId('composer')).not.toBeInTheDocument()
    })

    it('lazy-loads behind the run-log skeleton, then renders the thread', async () => {
        setValues({ currentRunStatus: 'in_progress' })
        render(<LazyRunViewer taskId="task-1" runId="run-1" interaction="read-only" />)
        // The Suspense fallback shows the shared skeleton while the impl chunk resolves...
        expect(screen.getByTestId('run-log-skeleton')).toBeInTheDocument()
        // ...then the lazily-imported viewer mounts and the thread appears.
        expect(await screen.findByTestId('thread')).toBeInTheDocument()
    })
})
