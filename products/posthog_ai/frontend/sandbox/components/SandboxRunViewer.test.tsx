import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import type { SandboxRunStatus } from '../sandboxStreamLogic'
import type { PermissionRequestRecord } from '../types/sandboxStreamTypes'
import { SandboxRunViewer } from './SandboxRunViewer'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    BindLogic: ({ children }: { children: React.ReactNode }) => children,
    useActions: jest.fn(),
    useValues: jest.fn(),
}))

jest.mock('../sandboxStreamLogic', () => ({
    sandboxStreamLogic: jest.fn(() => ({ __mock: 'sandboxStreamLogic' })),
    isTerminalRunStatus: (status: string | null) =>
        status != null && ['completed', 'failed', 'cancelled'].includes(status),
}))

jest.mock('./SandboxThreadView', () => ({ SandboxThreadView: () => <div data-attr="thread" /> }))
jest.mock('./SandboxResourcesBar', () => ({ SandboxResourcesBar: () => <div data-attr="resources" /> }))
jest.mock('./SandboxContextUsage', () => ({ SandboxContextUsage: () => <div data-attr="context" /> }))
jest.mock('./SandboxPermissionInput', () => ({ SandboxPermissionInput: () => <div data-attr="permission" /> }))
jest.mock('./SandboxQuestionInput', () => ({ SandboxQuestionInput: () => <div data-attr="question" /> }))

const composerProps = {
    composerValue: '',
    onComposerChange: jest.fn(),
    onComposerSubmit: jest.fn(),
    composerLoading: false,
}

function setValues(
    overrides: Partial<{
        currentRunStatus: SandboxRunStatus | null
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

describe('SandboxRunViewer', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        ;(useActions as jest.Mock).mockReturnValue({ bootstrapRun: jest.fn(), reset: jest.fn() })
        setValues({})
    })

    afterEach(() => {
        cleanup()
    })

    const renderLive = (statusOrOverrides: SandboxRunStatus | null | Parameters<typeof setValues>[0]): void => {
        if (typeof statusOrOverrides === 'object' && statusOrOverrides !== null) {
            setValues(statusOrOverrides)
        } else {
            setValues({ currentRunStatus: statusOrOverrides as SandboxRunStatus | null })
        }
        render(<SandboxRunViewer taskId="task-1" runId="run-1" interaction="live" {...composerProps} />)
    }

    it.each<SandboxRunStatus>(['queued', 'in_progress'])('shows the composer for an active run (%s)', (status) => {
        renderLive(status)
        expect(screen.getByTestId('composer')).toBeInTheDocument()
    })

    it('does not show the composer during the null bootstrap window', () => {
        renderLive(null)
        expect(screen.queryByTestId('composer')).not.toBeInTheDocument()
        // The thread still renders while bootstrapping.
        expect(screen.getByTestId('thread')).toBeInTheDocument()
    })

    it.each<SandboxRunStatus>(['completed', 'failed', 'cancelled'])(
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
        render(<SandboxRunViewer taskId="task-1" runId="run-1" interaction="read-only" />)
        expect(screen.queryByTestId('composer')).not.toBeInTheDocument()
        expect(screen.queryByTestId('resources')).not.toBeInTheDocument()
        expect(screen.getByTestId('thread')).toBeInTheDocument()
    })

    it('omits the composer in live mode when no composer props are supplied', () => {
        setValues({ currentRunStatus: 'in_progress' })
        render(<SandboxRunViewer taskId="task-1" runId="run-1" interaction="live" />)
        expect(screen.queryByTestId('composer')).not.toBeInTheDocument()
    })
})
