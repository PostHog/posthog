import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { taskComposerLogic } from '../composer/taskComposerLogic'
import { taskDetailSceneLogic } from '../logics/taskDetailSceneLogic'
import { TaskRun, TaskRunEnvironment, TaskRunStatus } from '../types'
import { TaskSessionView } from './TaskSessionView'

jest.mock('../composer/api', () => ({
    sendRunCommand: jest.fn().mockResolvedValue(undefined),
    uploadRunAttachments: jest.fn().mockResolvedValue([]),
    uploadStagedAttachments: jest.fn().mockResolvedValue([]),
    resumeRun: jest.fn().mockResolvedValue('run-2'),
}))

const TASK_ID = 'task-1'
const RUN_ID = 'run-1'

function makeRun(status: TaskRunStatus): TaskRun {
    return {
        id: RUN_ID,
        task: TASK_ID,
        stage: null,
        branch: null,
        status,
        environment: TaskRunEnvironment.CLOUD,
        log_url: null,
        error_message: null,
        output: null,
        state: {},
        artifacts: [],
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        completed_at: null,
    }
}

function fetchMock(run: TaskRun): typeof fetch {
    return jest.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (/\/runs\/[^/]+\/logs\/$/.test(url)) {
            return Promise.resolve(new Response(''))
        }
        if (/\/runs\/[^/]+\/$/.test(url)) {
            return Promise.resolve(
                new Response(JSON.stringify(run), { headers: { 'Content-Type': 'application/json' } })
            )
        }
        if (url.endsWith('/runs/')) {
            return Promise.resolve(
                new Response(JSON.stringify({ results: [] }), { headers: { 'Content-Type': 'application/json' } })
            )
        }
        if (/\/tasks\/[^/]+\/$/.test(url)) {
            return Promise.resolve(
                new Response(JSON.stringify({ id: TASK_ID }), { headers: { 'Content-Type': 'application/json' } })
            )
        }
        return Promise.resolve(new Response(''))
    }) as typeof fetch
}

describe('TaskSessionView', () => {
    const originalFetch = global.fetch
    let detailLogic: ReturnType<typeof taskDetailSceneLogic.build>
    let composer: ReturnType<typeof taskComposerLogic.build>

    async function setup(status: TaskRunStatus): Promise<TaskRun> {
        const run = makeRun(status)
        global.fetch = fetchMock(run)
        detailLogic = taskDetailSceneLogic({ taskId: TASK_ID })
        detailLogic.mount()
        await expectLogic(detailLogic).toFinishAllListeners()
        detailLogic.actions.setSelectedRunId(RUN_ID, TASK_ID)
        detailLogic.actions.loadSelectedRunSuccess(run)
        await expectLogic(detailLogic).toFinishAllListeners()
        composer = taskComposerLogic({ taskId: TASK_ID })
        composer.mount()
        await expectLogic(composer).toFinishAllListeners()
        return run
    }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        composer?.unmount()
        detailLogic?.unmount()
        global.fetch = originalFetch
    })

    it('renders the composer without crashing for an in-progress run', async () => {
        const run = await setup(TaskRunStatus.IN_PROGRESS)
        render(
            <TaskSessionView
                taskId={TASK_ID}
                logs=""
                logsLoading={false}
                events={[]}
                isPolling={false}
                isStreaming={false}
                run={run}
            />
        )
        // The composer (its textarea placeholder) renders for a non-terminal run.
        expect(screen.getByPlaceholderText(/follow-up|run starts|continue this task/i)).toBeInTheDocument()
    })

    it('renders a queued message instead of crashing on undefined queuedMessages', async () => {
        const run = await setup(TaskRunStatus.QUEUED)
        composer.actions.enqueueLocal({ id: 'q1', content: 'queued while booting', queuedAt: 1 })
        await expectLogic(composer).toFinishAllListeners()

        render(
            <TaskSessionView
                taskId={TASK_ID}
                logs=""
                logsLoading={false}
                events={[]}
                isPolling={true}
                isStreaming={false}
                run={run}
            />
        )
        expect(screen.getByText('queued while booting')).toBeInTheDocument()
    })

    it('shows the resume composer for a terminal run', async () => {
        const run = await setup(TaskRunStatus.COMPLETED)
        render(
            <TaskSessionView
                taskId={TASK_ID}
                logs=""
                logsLoading={false}
                events={[]}
                isPolling={false}
                isStreaming={false}
                run={run}
            />
        )
        // Terminal runs still show the composer (in resume mode), not a crash.
        expect(screen.getByPlaceholderText(/continue this task/i)).toBeInTheDocument()
    })
})
