import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { projectLogic } from 'scenes/projectLogic'

import { initKeaTests } from '~/test/init'

import { tasksRunCreate, tasksRunsCommandCreate } from 'products/tasks/frontend/generated/api'

import { runInteractionLogic } from './runInteractionLogic'
import { runStreamLogic } from './runStreamLogic'

// Minimal kea stub for the shared sandbox stream logic — gives the test full control over the busy gate
// (`isThinking`) and `currentRunStatus`, and lets us fire `markTurnComplete` and observe `pushHumanMessage`
// without the real SSE machinery.
jest.mock('./runStreamLogic', () => {
    const { kea, actions, key, path, props, reducers } = jest.requireActual('kea')
    const stub = kea([
        path(['test', 'runStreamLogicStub']),
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
        runStreamLogic: stub,
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

describe('runInteractionLogic', () => {
    let logic: ReturnType<typeof runInteractionLogic.build>
    let stream: ReturnType<typeof runStreamLogic.build>
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

    const setConfigCommand = (configId: string, value: string): [string, string, string, Record<string, unknown>] => [
        '997',
        TASK_ID,
        RUN_ID,
        { jsonrpc: '2.0', method: 'set_config_option', params: { configId, value } },
    ]

    beforeEach(() => {
        jest.clearAllMocks()
        ;(tasksRunsCommandCreate as jest.Mock).mockResolvedValue({})
        ;(tasksRunCreate as jest.Mock).mockResolvedValue({ latest_run: 'run-2' })
        initKeaTests()
        project = projectLogic()
        project.mount()
        stream = runStreamLogic({ streamKey: RUN_ID })
        stream.mount()
        logic = runInteractionLogic({ taskId: TASK_ID, runId: RUN_ID, onRunStarted })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        stream?.unmount()
        project?.unmount()
    })

    it('sends immediately and echoes the message when the agent is idle', async () => {
        setThinking(false)
        logic.actions.setComposerFormValues({ draft: 'ship it' })

        await expectLogic(logic, () => {
            logic.actions.submitComposerForm()
        }).toFinishAllListeners()

        expect(tasksRunsCommandCreate).toHaveBeenCalledWith(...userMessageCommand('ship it'))
        await expectLogic(stream).toDispatchActions(['pushHumanMessage'])
        expect(logic.values.composerForm.draft).toBe('')
        expect(logic.values.queuedMessages).toEqual([])
    })

    it('does not send any command when the model or effort is picked', async () => {
        setThinking(false)
        logic.actions.setModel('claude-sonnet-4-6')
        logic.actions.setEffort('low')

        await expectLogic(logic).toFinishAllListeners()

        // Picking is client-side only now — nothing is synced until the message is sent.
        expect(tasksRunsCommandCreate).not.toHaveBeenCalled()
        expect(logic.values.selectedModel).toBe('claude-sonnet-4-6')
        expect(logic.values.selectedEffort).toBe('low')
    })

    it('syncs a changed model to the agent right before the message, and only when it changed', async () => {
        setThinking(false)
        logic.actions.setModel('claude-sonnet-4-6')
        logic.actions.setComposerFormValues({ draft: 'ship it' })

        await expectLogic(logic, () => {
            logic.actions.submitComposerForm()
        }).toFinishAllListeners()

        // The config sync lands before the message, never inside it.
        expect((tasksRunsCommandCreate as jest.Mock).mock.calls).toEqual([
            setConfigCommand('model', 'claude-sonnet-4-6'),
            userMessageCommand('ship it'),
        ])

        // A follow-up with the same selection re-syncs nothing — just the message.
        ;(tasksRunsCommandCreate as jest.Mock).mockClear()
        logic.actions.setComposerFormValues({ draft: 'again' })

        await expectLogic(logic, () => {
            logic.actions.submitComposerForm()
        }).toFinishAllListeners()

        expect((tasksRunsCommandCreate as jest.Mock).mock.calls).toEqual([userMessageCommand('again')])
    })

    it('stages the message in the queue while the agent is busy', async () => {
        setThinking(true)
        logic.actions.setComposerFormValues({ draft: 'follow up' })

        await expectLogic(logic, () => {
            logic.actions.submitComposerForm()
        }).toFinishAllListeners()

        expect(tasksRunsCommandCreate).not.toHaveBeenCalled()
        expect(logic.values.composerForm.draft).toBe('')
        expect(logic.values.queuedMessages).toEqual([{ id: expect.any(String), content: 'follow up' }])
    })

    it('concatenates follow-ups into a single staged message and flushes it when the turn completes', async () => {
        setThinking(true)
        logic.actions.setComposerFormValues({ draft: 'first' })
        logic.actions.submitComposerForm()
        logic.actions.setComposerFormValues({ draft: 'second' })
        logic.actions.submitComposerForm()
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
        logic.actions.setComposerFormValues({ draft: 'typo' })
        logic.actions.submitComposerForm()
        const { id } = logic.values.queuedMessages[0]

        logic.actions.updateQueuedMessage(id, 'fixed')
        expect(logic.values.queuedMessages).toEqual([{ id, content: 'fixed' }])

        logic.actions.removeQueuedMessage(id)
        expect(logic.values.queuedMessages).toEqual([])
    })

    it('keeps the draft and toasts when the send fails', async () => {
        ;(tasksRunsCommandCreate as jest.Mock).mockRejectedValue(new Error('boom'))
        setThinking(false)
        logic.actions.setComposerFormValues({ draft: 'ship it' })

        await expectLogic(logic, () => {
            logic.actions.submitComposerForm()
        }).toFinishAllListeners()

        expect(lemonToast.error).toHaveBeenCalled()
        expect(logic.values.composerForm.draft).toBe('ship it')
        expect(logic.values.sending).toBe(false)
    })

    it('starts a fresh run seeded with the message when the run is terminal', async () => {
        setStatus('completed')
        logic.actions.setComposerFormValues({ draft: 'continue from here' })

        await expectLogic(logic, () => {
            logic.actions.submitComposerForm()
        }).toFinishAllListeners()

        // No live-run signal for a finished run — it resumes into a new run instead.
        expect(tasksRunsCommandCreate).not.toHaveBeenCalled()
        expect(tasksRunCreate).toHaveBeenCalledWith('997', TASK_ID, {
            runtime_adapter: 'claude',
            model: 'claude-opus-4-8',
            reasoning_effort: 'high',
            resume_from_run_id: RUN_ID,
            pending_user_message: 'continue from here',
        })
        expect(onRunStarted).toHaveBeenCalledWith('run-2')
        expect(logic.values.queuedMessages).toEqual([])
        expect(logic.values.composerForm.draft).toBe('')
    })

    it('keeps the draft and toasts when starting a new run fails', async () => {
        ;(tasksRunCreate as jest.Mock).mockRejectedValue(new Error('boom'))
        setStatus('completed')
        logic.actions.setComposerFormValues({ draft: 'continue from here' })

        await expectLogic(logic, () => {
            logic.actions.submitComposerForm()
        }).toFinishAllListeners()

        expect(lemonToast.error).toHaveBeenCalled()
        expect(onRunStarted).not.toHaveBeenCalled()
        expect(logic.values.composerForm.draft).toBe('continue from here')
    })

    const setProjectId = (id: number | null): void =>
        (project.actions as unknown as { setCurrentProjectId: (id: number | null) => void }).setCurrentProjectId(id)

    it('no-ops and keeps the draft when submitting idle without a current project', async () => {
        setProjectId(null)
        setThinking(false)
        logic.actions.setComposerFormValues({ draft: 'ship it' })

        await expectLogic(logic, () => {
            logic.actions.submitComposerForm()
        }).toFinishAllListeners()

        // Nothing can be sent without a project — the draft is preserved rather than dropped.
        expect(tasksRunsCommandCreate).not.toHaveBeenCalled()
        expect(logic.values.composerForm.draft).toBe('ship it')
        expect(logic.values.queuedMessages).toEqual([])
    })

    it('stages the message while busy without a current project and never silently sends it', async () => {
        setProjectId(null)
        setThinking(true)
        logic.actions.setComposerFormValues({ draft: 'follow up' })

        await expectLogic(logic, () => {
            logic.actions.submitComposerForm()
        }).toFinishAllListeners()

        // Busy + no project: the message is staged, and the guarded flush keeps it there rather than POSTing.
        expect(tasksRunsCommandCreate).not.toHaveBeenCalled()
        expect(logic.values.composerForm.draft).toBe('')
        expect(logic.values.queuedMessages).toEqual([{ id: expect.any(String), content: 'follow up' }])
    })

    it('keeps text typed into the composer during an in-flight draft send instead of clobbering it on success', async () => {
        let resolveSend: () => void = () => {}
        ;(tasksRunsCommandCreate as jest.Mock).mockReturnValue(
            new Promise<void>((resolve) => {
                resolveSend = () => resolve()
            })
        )

        // Idle send straight from the draft: the draft is cleared up-front, before the await.
        setThinking(false)
        logic.actions.setComposerFormValues({ draft: 'ship it' })
        logic.actions.submitComposerForm()
        expect(logic.values.sending).toBe(true)
        expect(logic.values.composerForm.draft).toBe('')

        // The user keeps typing while the send is in flight.
        logic.actions.setComposerFormValues({ draft: 'next thought' })

        await expectLogic(logic, () => {
            resolveSend()
        }).toFinishAllListeners()

        // Success leaves the composer alone — the newly typed text survives rather than being wiped.
        expect(tasksRunsCommandCreate).toHaveBeenCalledWith(...userMessageCommand('ship it'))
        expect(logic.values.composerForm.draft).toBe('next thought')
    })

    it('restores a failed draft send ahead of text typed during the send, preserving order', async () => {
        let rejectSend: () => void = () => {}
        ;(tasksRunsCommandCreate as jest.Mock).mockReturnValue(
            new Promise<void>((_, reject) => {
                rejectSend = () => reject(new Error('boom'))
            })
        )

        setThinking(false)
        logic.actions.setComposerFormValues({ draft: 'ship it' })
        logic.actions.submitComposerForm()
        expect(logic.values.composerForm.draft).toBe('')

        logic.actions.setComposerFormValues({ draft: 'next thought' })

        await expectLogic(logic, () => {
            rejectSend()
        }).toFinishAllListeners()

        // The failed send puts the original back in front of what was typed since, so nothing is lost.
        expect(lemonToast.error).toHaveBeenCalled()
        expect(logic.values.composerForm.draft).toBe('ship it\n\nnext thought')
    })

    it('keeps a follow-up typed during an in-flight queue flush instead of clearing it with the send', async () => {
        let resolveSend: () => void = () => {}
        ;(tasksRunsCommandCreate as jest.Mock).mockReturnValue(
            new Promise<void>((resolve) => {
                resolveSend = () => resolve()
            })
        )

        // Stage a message while busy, then complete the turn to start flushing it.
        setThinking(true)
        logic.actions.setComposerFormValues({ draft: 'first' })
        logic.actions.submitComposerForm()

        setThinking(false)
        stream.actions.markTurnComplete()
        // The flush is now in flight: the buffer is cleared up-front so a new follow-up stages cleanly.
        expect(logic.values.sending).toBe(true)
        expect(logic.values.queuedMessages).toEqual([])

        logic.actions.setComposerFormValues({ draft: 'second' })
        logic.actions.submitComposerForm()
        expect(logic.values.queuedMessages).toEqual([{ id: expect.any(String), content: 'second' }])

        await expectLogic(logic, () => {
            resolveSend()
        }).toFinishAllListeners()

        // Only the first message was sent; the follow-up survives the flush rather than being lost.
        expect(tasksRunsCommandCreate).toHaveBeenCalledTimes(1)
        expect(tasksRunsCommandCreate).toHaveBeenCalledWith(...userMessageCommand('first'))
        expect(logic.values.queuedMessages).toEqual([{ id: expect.any(String), content: 'second' }])
    })

    it('re-stages a queued message ahead of newer follow-ups when its flush fails', async () => {
        let rejectSend: () => void = () => {}
        ;(tasksRunsCommandCreate as jest.Mock).mockReturnValue(
            new Promise<void>((_, reject) => {
                rejectSend = () => reject(new Error('boom'))
            })
        )

        setThinking(true)
        logic.actions.setComposerFormValues({ draft: 'first' })
        logic.actions.submitComposerForm()

        setThinking(false)
        stream.actions.markTurnComplete()
        expect(logic.values.queuedMessages).toEqual([])

        // A follow-up staged while the flush is in flight.
        logic.actions.setComposerFormValues({ draft: 'second' })
        logic.actions.submitComposerForm()

        await expectLogic(logic, () => {
            rejectSend()
        }).toFinishAllListeners()

        // The failed send re-stages 'first' in front of 'second', preserving order, and toasts.
        expect(lemonToast.error).toHaveBeenCalled()
        expect(logic.values.queuedMessages).toEqual([{ id: expect.any(String), content: 'first\n\nsecond' }])
    })

    it('no-ops on submit with an empty draft', async () => {
        await expectLogic(logic, () => {
            logic.actions.submitComposerForm()
        }).toFinishAllListeners()

        expect(tasksRunsCommandCreate).not.toHaveBeenCalled()
        expect(logic.values.queuedMessages).toEqual([])
    })
})
