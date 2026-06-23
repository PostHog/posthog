import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { projectLogic } from 'scenes/projectLogic'

import { initKeaTests } from '~/test/init'

import { sandboxStreamLogic } from 'products/posthog_ai/frontend/sandbox'

import { tasksRunsCommandCreate } from '../generated/api'
import { taskRunChatLogic } from './taskRunChatLogic'

// Minimal kea stub for the shared sandbox stream logic — gives the test full control over
// `currentRunStatus` and lets us observe `pushHumanMessage` without the real SSE machinery.
jest.mock('products/posthog_ai/frontend/sandbox', () => {
    const { kea, actions, key, path, props, reducers } = jest.requireActual('kea')
    const stub = kea([
        path(['test', 'sandboxStreamLogicStub']),
        props({}),
        key((p: { streamKey: string }) => p.streamKey),
        actions({
            pushHumanMessage: (content: string) => ({ content }),
            setStubStatus: (status: string | null) => ({ status }),
        }),
        reducers({
            currentRunStatus: [
                null,
                {
                    setStubStatus: (_: string | null, { status }: { status: string | null }) => status,
                },
            ],
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

jest.mock('../generated/api', () => ({
    tasksRunsCommandCreate: jest.fn(),
}))

jest.mock('lib/lemon-ui/LemonToast', () => ({
    lemonToast: { error: jest.fn() },
}))

describe('taskRunChatLogic', () => {
    let logic: ReturnType<typeof taskRunChatLogic.build>
    let stream: ReturnType<typeof sandboxStreamLogic.build>
    let project: ReturnType<typeof projectLogic.build>

    const TASK_ID = 'task-1'
    const RUN_ID = 'run-1'

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        project = projectLogic()
        project.mount()
        stream = sandboxStreamLogic({ streamKey: RUN_ID })
        stream.mount()
        logic = taskRunChatLogic({ taskId: TASK_ID, runId: RUN_ID })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        stream?.unmount()
        project?.unmount()
    })

    it('clears the draft and echoes the human message on a successful send', async () => {
        ;(tasksRunsCommandCreate as jest.Mock).mockResolvedValue({})
        logic.actions.setComposerDraft('ship it')

        await expectLogic(logic, () => {
            logic.actions.sendMessage('ship it')
        }).toFinishAllListeners()

        expect(tasksRunsCommandCreate).toHaveBeenCalledWith('997', TASK_ID, RUN_ID, {
            jsonrpc: '2.0',
            method: 'user_message',
            params: { content: 'ship it' },
        })
        await expectLogic(stream).toDispatchActions(['pushHumanMessage'])
        expect(logic.values.composerDraft).toBe('')
        expect(logic.values.sendingMessage).toBe(false)
    })

    it('keeps the draft and toasts when the send fails', async () => {
        ;(tasksRunsCommandCreate as jest.Mock).mockRejectedValue(new Error('boom'))
        logic.actions.setComposerDraft('ship it')

        await expectLogic(logic, () => {
            logic.actions.sendMessage('ship it')
        }).toFinishAllListeners()

        expect(lemonToast.error).toHaveBeenCalled()
        expect(logic.values.composerDraft).toBe('ship it')
        expect(logic.values.sendingMessage).toBe(false)
    })

    it('no-ops without a current project and preserves the draft', async () => {
        project.actions.setCurrentProjectId(null)
        logic.actions.setComposerDraft('ship it')

        await expectLogic(logic, () => {
            logic.actions.sendMessage('ship it')
        }).toFinishAllListeners()

        expect(tasksRunsCommandCreate).not.toHaveBeenCalled()
        expect(logic.values.composerDraft).toBe('ship it')
    })

    it('no-ops for a terminal run', async () => {
        stream.actions.setStubStatus('completed')
        logic.actions.setComposerDraft('ship it')

        await expectLogic(logic, () => {
            logic.actions.sendMessage('ship it')
        }).toFinishAllListeners()

        expect(tasksRunsCommandCreate).not.toHaveBeenCalled()
        expect(logic.values.composerDraft).toBe('ship it')
    })

    it('no-ops for an empty message', async () => {
        await expectLogic(logic, () => {
            logic.actions.sendMessage('   ')
        }).toFinishAllListeners()

        expect(tasksRunsCommandCreate).not.toHaveBeenCalled()
    })
})
