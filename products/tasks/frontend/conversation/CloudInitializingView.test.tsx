import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'

import { TaskRun, TaskRunEnvironment, TaskRunStatus } from '../types'
import CloudInitializingView from './CloudInitializingView'

const REVEAL_DELAY_MS = 2000

function makeRun(overrides: Partial<TaskRun> = {}): TaskRun {
    return {
        id: 'run-1',
        task: 'task-1',
        stage: null,
        branch: null,
        status: TaskRunStatus.QUEUED,
        environment: TaskRunEnvironment.CLOUD,
        log_url: null,
        error_message: null,
        output: null,
        state: {},
        artifacts: [],
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        completed_at: null,
        ...overrides,
    }
}

function reveal(): void {
    act(() => {
        jest.advanceTimersByTime(REVEAL_DELAY_MS)
    })
}

describe('CloudInitializingView', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    it('shows only a spinner before the reveal delay elapses', () => {
        const { container } = render(<CloudInitializingView run={makeRun()} />)

        expect(container.querySelectorAll('svg.Spinner')).toHaveLength(1)
        expect(screen.queryByText('Waiting in the queue…')).not.toBeInTheDocument()

        act(() => {
            jest.advanceTimersByTime(REVEAL_DELAY_MS - 1)
        })
        expect(screen.queryByText('Waiting in the queue…')).not.toBeInTheDocument()

        act(() => {
            jest.advanceTimersByTime(1)
        })
        expect(screen.getByText('Waiting in the queue…')).toBeInTheDocument()
    })

    it.each([
        ['null run', null, 'Getting things ready…', 'Connecting to your cloud runner.'],
        [
            'queued stage',
            makeRun({ stage: 'queued' }),
            'Waiting in the queue…',
            'Reserving a cloud sandbox — this can take a few seconds.',
        ],
        [
            'in_progress stage',
            makeRun({ stage: 'in_progress' }),
            'Starting the sandbox…',
            'Connecting to your cloud runner.',
        ],
        [
            'queued status fallback when stage is null',
            makeRun({ stage: null, status: TaskRunStatus.QUEUED }),
            'Waiting in the queue…',
            'Reserving a cloud sandbox — this can take a few seconds.',
        ],
        [
            'in_progress status fallback when stage is null',
            makeRun({ stage: null, status: TaskRunStatus.IN_PROGRESS }),
            'Starting the sandbox…',
            'Connecting to your cloud runner.',
        ],
        [
            'unknown stage',
            makeRun({ stage: 'provisioning', status: TaskRunStatus.IN_PROGRESS }),
            'Getting things ready…',
            'Connecting to your cloud runner.',
        ],
    ])('shows the expected copy for %s', (_label: string, run: TaskRun | null, heading: string, subtitle: string) => {
        render(<CloudInitializingView run={run} />)
        reveal()

        expect(screen.getByText(heading)).toBeInTheDocument()
        expect(screen.getByText(subtitle)).toBeInTheDocument()
    })

    it('renders an inline spinner next to the heading after the reveal', () => {
        const { container } = render(<CloudInitializingView run={makeRun({ stage: 'queued' })} />)
        reveal()

        const spinners = container.querySelectorAll('svg.Spinner')
        expect(spinners).toHaveLength(1)

        const heading = screen.getByText('Waiting in the queue…')
        expect(heading.parentElement).toContainElement(spinners[0] as HTMLElement)
    })

    it('stacks the heading above the subtitle in a centered column', () => {
        render(<CloudInitializingView run={makeRun({ stage: 'queued' })} />)
        reveal()

        const heading = screen.getByText('Waiting in the queue…')
        const subtitle = screen.getByText('Reserving a cloud sandbox — this can take a few seconds.')
        const column = heading.parentElement?.parentElement

        expect(column).toContainElement(subtitle)
        expect(column).toHaveClass('flex-col', 'items-center')
    })
})
