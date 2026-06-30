import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import type { RunStatus } from '../logics/runStreamLogic'
import type { PermissionRequestRecord } from '../types/streamTypes'
import { RunSurface } from './RunSurfaceImpl'

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
        task: null,
        taskLoading: false,
        ...overrides,
    })
}

// A live surface with the composer slot rendering an identifiable composer child.
function renderLiveWithComposer(statusOrOverrides: RunStatus | null | Parameters<typeof setValues>[0]): void {
    if (typeof statusOrOverrides === 'object' && statusOrOverrides !== null) {
        setValues(statusOrOverrides)
    } else {
        setValues({ currentRunStatus: statusOrOverrides as RunStatus | null })
    }
    render(
        <RunSurface.Root taskId="task-1" runId="run-1" interaction="live">
            <RunSurface.Thread />
            <RunSurface.Composer>
                <div data-attr="composer-child" />
            </RunSurface.Composer>
        </RunSurface.Root>
    )
}

describe('RunSurface', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        ;(useActions as jest.Mock).mockReturnValue({ bootstrapRun: jest.fn(), reset: jest.fn(), loadTask: jest.fn() })
        setValues({})
    })

    afterEach(() => {
        cleanup()
    })

    describe('Composer slot', () => {
        it.each<RunStatus>(['queued', 'in_progress'])(
            'renders the composer children for an active run (%s)',
            (status) => {
                renderLiveWithComposer(status)
                expect(screen.getByTestId('composer')).toBeInTheDocument()
                expect(screen.getByTestId('composer-child')).toBeInTheDocument()
            }
        )

        it.each<RunStatus>(['completed', 'failed', 'cancelled'])(
            'renders the composer children for a terminal run so a new run can be started (%s)',
            (status) => {
                renderLiveWithComposer(status)
                expect(screen.getByTestId('composer')).toBeInTheDocument()
            }
        )

        it('hides the composer during the null bootstrap window', () => {
            renderLiveWithComposer(null)
            expect(screen.queryByTestId('composer')).not.toBeInTheDocument()
            // The thread still renders while bootstrapping.
            expect(screen.getByTestId('thread')).toBeInTheDocument()
        })

        it('renders the permission input instead of the composer when a request is pending', () => {
            renderLiveWithComposer({
                currentRunStatus: 'in_progress',
                pendingPermissionRequest: { requestId: 'r1' } as PermissionRequestRecord,
            })
            expect(screen.getByTestId('permission')).toBeInTheDocument()
            expect(screen.queryByTestId('composer')).not.toBeInTheDocument()
        })

        it('renders the question input when the pending request carries questions', () => {
            renderLiveWithComposer({
                currentRunStatus: 'in_progress',
                pendingPermissionRequest: {
                    requestId: 'r1',
                    questions: [{ question: 'q' }],
                } as PermissionRequestRecord,
            })
            expect(screen.getByTestId('question')).toBeInTheDocument()
            expect(screen.queryByTestId('composer')).not.toBeInTheDocument()
        })

        it('renders nothing in read-only mode', () => {
            setValues({ currentRunStatus: 'in_progress' })
            render(
                <RunSurface.Root taskId="task-1" runId="run-1" interaction="read-only">
                    <RunSurface.Composer>
                        <div data-attr="composer-child" />
                    </RunSurface.Composer>
                </RunSurface.Root>
            )
            expect(screen.queryByTestId('composer')).not.toBeInTheDocument()
            expect(screen.queryByTestId('composer-child')).not.toBeInTheDocument()
        })

        it('renders only the prompt-when-pending (never a composer) when no children are supplied', () => {
            setValues({
                currentRunStatus: 'in_progress',
                pendingPermissionRequest: { requestId: 'r1' } as PermissionRequestRecord,
            })
            render(
                <RunSurface.Root taskId="task-1" runId="run-1" interaction="live">
                    <RunSurface.Composer />
                </RunSurface.Root>
            )
            expect(screen.getByTestId('permission')).toBeInTheDocument()
            expect(screen.queryByTestId('composer')).not.toBeInTheDocument()
        })

        it('renders nothing with no children once settled and no request pending', () => {
            setValues({ currentRunStatus: 'in_progress' })
            render(
                <RunSurface.Root taskId="task-1" runId="run-1" interaction="live">
                    <RunSurface.Composer />
                </RunSurface.Root>
            )
            expect(screen.queryByTestId('composer')).not.toBeInTheDocument()
            expect(screen.queryByTestId('permission')).not.toBeInTheDocument()
        })
    })

    describe('Thread slot', () => {
        it('shows the run-log skeleton while bootstrapping with no thread items yet', () => {
            setValues({ bootstrapLoading: true, threadItems: [] })
            render(
                <RunSurface.Root taskId="task-1" runId="run-1" interaction="read-only">
                    <RunSurface.Thread />
                </RunSurface.Root>
            )
            expect(screen.getByTestId('run-log-skeleton')).toBeInTheDocument()
            expect(screen.queryByTestId('thread')).not.toBeInTheDocument()
        })

        it('swaps the skeleton for the thread once items arrive', () => {
            setValues({ bootstrapLoading: true, threadItems: [{ id: 'x' }] })
            render(
                <RunSurface.Root taskId="task-1" runId="run-1" interaction="read-only">
                    <RunSurface.Thread />
                </RunSurface.Root>
            )
            expect(screen.getByTestId('thread')).toBeInTheDocument()
            expect(screen.queryByTestId('run-log-skeleton')).not.toBeInTheDocument()
        })
    })
})
