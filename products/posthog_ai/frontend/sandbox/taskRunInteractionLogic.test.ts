import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { projectLogic } from 'scenes/projectLogic'

import { initKeaTests } from '~/test/init'

import { tasksRunCreate, tasksRunsCommandCreate } from 'products/tasks/frontend/generated/api'

import { sandboxStreamLogic } from './sandboxStreamLogic'
import { taskRunInteractionLogic } from './taskRunInteractionLogic'

// Minimal kea stub for the shared sandbox stream logic — gives the test full control over the busy gate
// (`isThinking`) and `currentRunStatus`, and lets us fire `markTurnComplete` and observe `pushHumanMessage`
// without the real SSE machinery.
jest.mock('./sandboxStreamLogic', () => {
    const { kea, actions, key, path, props, reducers } = jest.requireActual('kea')
    const stub = kea([
        path(['test', 'sandboxStreamLogicStub']),
        props({}),
        key((p: { streamKey: string }) => p.streamKey),
        actions({
            pushHumanMessage: (content: string) => ({ content }),
            respondToPermission: (payload: unknown) => ({ payload }),
            cancelRun: (run?: unknown) => ({ run }),
            markTurnComplete: true,
            setStubStatus: (status: string | null) => ({ status }),
            setStubThinking: (thinking: boolean) => ({ thinking }),
        }),
        reducers({
            currentRunStatus: [
                'in_progress',
                {
                    setStubStatus: (_: string | null, { status }: { status: string | null }) => status,
                },
            ],
            isThinking: [
                false,
                {
                    setStubThinking: (_: boolean, { thinking }: { thinking: boolean }) => thinking,
                },
            ],
            pendingPermissionRequest: [null, {}],
            respondingToPermission: [false, {}],
        }),
    ])
    return {
        sandboxStreamLogic: stub,
        isTerminalRunStatus: (status: string | null) =>
            status != null && ['completed', 'failed', 'cancelled'].includes(status),
    }
})

jest.mock('scenes/projectLogic', () => {
    const { kea, actions, path, reducers } = jest.requireActual('kea')
    const stub = kea([
        path(['test', 'projectLogicStub']),
        actions({ setCurrentProjectId: (id: number | null) => ({ id }) }),
        reducers({
            currentProjectId: [
                997,
                {
                    setCurrentProjectId: (_: number | null, { id }: { id: number | null }) => id,
                },
            ],
        }),
    ])
    return { projectLogic: stub }
})

jest.mock('products/tasks/frontend/generated/api', () => ({
    tasksRunsCommandCreate: jest.fn(),
    tasksRunCreate: jest.fn(),
}))

jest.mock('lib/lemon-ui/LemonToast', () => ({
    lemonToast: { error: jest.fn() },
}))

describe('taskRunInteractionLogic', () => {
    let logic: ReturnType<typeof taskRunInteractionLogic.build>
    let stream: ReturnType<typeof sandboxStreamLogic.build>
    let project: ReturnType<typeof projectLogic.build>

    const TASK_ID = 'task-1'
    const RUN_ID = 'run-1'
    const onRunStarted = jest.fn()

    // `setStubStatus` / `setStubThinking` exist only on the jest-mocked stub, not the real logic type.
    const setStatus = (status: string | null): void =>
        (stream.actions as unknown as { setStubStatus: (status: string | null) => void }).setStubStatus(status)
    const setThinking = (thinking: boolean): void =>
        (stream.actions as unknown as { setStubThinking: (thinking: boolean) => void }).setStubThinking(thinking)

    const userMessageCommand = (content: string): [string, string, string, Record<string, unknown>] => [
        '997',
        TASK_ID,
        RUN_ID,
        { jsonrpc: '2.0', method: 'user_message', params: { content } },
    ]

    beforeEach(() => {
        jest.clearAllMocks()
        ;(tasksRunsCommandCreate as jest.Mock).mockResolvedValue({})
        ;(tasksRunCreate as jest.Mock).mockResolvedValue({ latest_run: 'run-2' })
        initKeaTests()
        project = projectLogic()
        project.mount()
        stream = sandboxStreamLogic({ streamKey: RUN_ID })
        stream.mount()
        logic = taskRunInteractionLogic({ taskId: TASK_ID, runId: RUN_ID, onRunStarted })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        stream?.unmount()
        project?.unmount()
    })

    it('sends immediately and echoes the message when the agent is idle', async () => {
        setThinking(false)
        logic.actions.setDraft('ship it')

        await expectLogic(logic, () => {
            logic.actions.submit()
        }).toFinishAllListeners()

        expect(tasksRunsCommandCreate).toHaveBeenCalledWith(...userMessageCommand('ship it'))
        await expectLogic(stream).toDispatchActions(['pushHumanMessage'])
        expect(logic.values.draft).toBe('')
        expect(logic.values.queuedMessages).toEqual([])
    })

    it('stages the message in the queue while the agent is busy', async () => {
        setThinking(true)
        logic.actions.setDraft('follow up')

        await expectLogic(logic, () => {
            logic.actions.submit()
        }).toFinishAllListeners()

        expect(tasksRunsCommandCreate).not.toHaveBeenCalled()
        expect(logic.values.draft).toBe('')
        expect(logic.values.queuedMessages).toEqual([{ id: expect.any(String), content: 'follow up' }])
    })

    it('concatenates follow-ups into a single staged message and flushes it when the turn completes', async () => {
        setThinking(true)
        logic.actions.setDraft('first')
        logic.actions.submit()
        logic.actions.setDraft('second')
        logic.actions.submit()
        // A second follow-up concatenates onto the first rather than fanning out into a separate message.
        expect(logic.values.queuedMessages).toEqual([{ id: expect.any(String), content: 'first\n\nsecond' }])

        // Turn completes → drain. The flush itself sends while idle.
        setThinking(false)
        await expectLogic(logic, () => {
            stream.actions.markTurnComplete()
        }).toFinishAllListeners()

        expect(tasksRunsCommandCreate).toHaveBeenCalledTimes(1)
        expect(tasksRunsCommandCreate).toHaveBeenCalledWith(...userMessageCommand('first\n\nsecond'))
        expect(logic.values.queuedMessages).toEqual([])
    })

    it('edits and removes staged messages', async () => {
        setThinking(true)
        logic.actions.setDraft('typo')
        logic.actions.submit()
        const { id } = logic.values.queuedMessages[0]

        logic.actions.updateQueuedMessage(id, 'fixed')
        expect(logic.values.queuedMessages).toEqual([{ id, content: 'fixed' }])

        logic.actions.removeQueuedMessage(id)
        expect(logic.values.queuedMessages).toEqual([])
    })

    it('keeps the draft and toasts when the send fails', async () => {
        ;(tasksRunsCommandCreate as jest.Mock).mockRejectedValue(new Error('boom'))
        setThinking(false)
        logic.actions.setDraft('ship it')

        await expectLogic(logic, () => {
            logic.actions.submit()
        }).toFinishAllListeners()

        expect(lemonToast.error).toHaveBeenCalled()
        expect(logic.values.draft).toBe('ship it')
        expect(logic.values.sending).toBe(false)
    })

    it('starts a fresh run seeded with the message when the run is terminal', async () => {
        setStatus('completed')
        logic.actions.setDraft('continue from here')

        await expectLogic(logic, () => {
            logic.actions.submit()
        }).toFinishAllListeners()

        // No live-run signal for a finished run — it resumes into a new run instead.
        expect(tasksRunsCommandCreate).not.toHaveBeenCalled()
        expect(tasksRunCreate).toHaveBeenCalledWith('997', TASK_ID, {
            resume_from_run_id: RUN_ID,
            pending_user_message: 'continue from here',
        })
        expect(onRunStarted).toHaveBeenCalledWith('run-2')
        expect(logic.values.queuedMessages).toEqual([])
        expect(logic.values.draft).toBe('')
    })

    it('keeps the draft and toasts when starting a new run fails', async () => {
        ;(tasksRunCreate as jest.Mock).mockRejectedValue(new Error('boom'))
        setStatus('completed')
        logic.actions.setDraft('continue from here')

        await expectLogic(logic, () => {
            logic.actions.submit()
        }).toFinishAllListeners()

        expect(lemonToast.error).toHaveBeenCalled()
        expect(onRunStarted).not.toHaveBeenCalled()
        expect(logic.values.draft).toBe('continue from here')
    })

    it('no-ops on submit with an empty draft', async () => {
        await expectLogic(logic, () => {
            logic.actions.submit()
        }).toFinishAllListeners()

        expect(tasksRunsCommandCreate).not.toHaveBeenCalled()
        expect(logic.values.queuedMessages).toEqual([])
    })
})
