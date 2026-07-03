import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import type { PermissionRequestRecord } from '../types/streamTypes'
import ReadonlyRunSurfaceImpl from './ReadonlyRunSurfaceImpl'

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

jest.mock('../logics/taskLogic', () => ({ taskLogic: jest.fn(() => ({ __mock: 'taskLogic' })) }))

jest.mock('./ThreadView', () => ({ ThreadView: () => <div data-attr="thread" /> }))
jest.mock('./ResourcesBar', () => ({ ResourcesBar: () => <div data-attr="resources" /> }))
jest.mock('./ContextUsageBar', () => ({ ContextUsageBar: () => <div data-attr="context" /> }))
jest.mock('./PermissionInput', () => ({ PermissionInput: () => <div data-attr="permission" /> }))
jest.mock('./QuestionInput', () => ({ QuestionInput: () => <div data-attr="question" /> }))
jest.mock('./RunLogSkeleton', () => ({ RunLogSkeleton: () => <div data-attr="run-log-skeleton" /> }))

function setValues(overrides: Partial<{ pendingPermissionRequest: PermissionRequestRecord | null }> = {}): void {
    ;(useValues as jest.Mock).mockReturnValue({
        bootstrapLoading: false,
        threadItems: [{ id: 'x' }],
        pendingPermissionRequest: null,
        currentRunStatus: 'in_progress',
        task: null,
        taskLoading: false,
        ...overrides,
    })
}

describe('ReadonlyRunSurfaceImpl', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        ;(useActions as jest.Mock).mockReturnValue({ bootstrapRun: jest.fn(), reset: jest.fn(), loadTask: jest.fn() })
        setValues()
    })

    afterEach(() => {
        cleanup()
    })

    it('renders only the thread in read-only mode — no meta bars, composer, or prompt', () => {
        render(<ReadonlyRunSurfaceImpl taskId="task-1" runId="run-1" interaction="read-only" />)
        expect(screen.getByTestId('thread')).toBeInTheDocument()
        expect(screen.queryByTestId('resources')).not.toBeInTheDocument()
        expect(screen.queryByTestId('context')).not.toBeInTheDocument()
        expect(screen.queryByTestId('composer')).not.toBeInTheDocument()
        expect(screen.queryByTestId('permission')).not.toBeInTheDocument()
        expect(screen.queryByTestId('question')).not.toBeInTheDocument()
    })

    it('renders the thread plus the resources bar for a live run, but never a composer or approval prompt', () => {
        render(<ReadonlyRunSurfaceImpl taskId="task-1" runId="run-1" interaction="live" />)
        expect(screen.getByTestId('thread')).toBeInTheDocument()
        expect(screen.getByTestId('resources')).toBeInTheDocument()
        // Context usage now rides the thread footer (inside ThreadView), not a standalone bar.
        expect(screen.queryByTestId('context')).not.toBeInTheDocument()
        expect(screen.queryByTestId('composer')).not.toBeInTheDocument()
        expect(screen.queryByTestId('permission')).not.toBeInTheDocument()
        expect(screen.queryByTestId('question')).not.toBeInTheDocument()
    })

    it('stays non-interactive for a live run even when a permission request is pending', () => {
        setValues({ pendingPermissionRequest: { requestId: 'r1' } as PermissionRequestRecord })
        render(<ReadonlyRunSurfaceImpl taskId="task-1" runId="run-1" interaction="live" />)
        expect(screen.queryByTestId('permission')).not.toBeInTheDocument()
        expect(screen.queryByTestId('question')).not.toBeInTheDocument()
        expect(screen.queryByTestId('composer')).not.toBeInTheDocument()
    })
})
