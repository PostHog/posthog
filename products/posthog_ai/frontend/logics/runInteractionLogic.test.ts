import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { projectLogic } from 'scenes/projectLogic'
import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'

import { initKeaTests } from '~/test/init'

import {
    tasksRunCreate,
    tasksRunsCancelCreate,
    tasksRunsClearConversationCreate,
    tasksRunsCommandCreate,
    tasksWarmResumeCreate,
} from 'products/tasks/frontend/generated/api'

import type { PermissionRequestRecord } from '../types/streamTypes'
import { contextItemLine } from '../utils/posthogContextBlock'
import { attachedContextLogic } from './attachedContextLogic'
import { runCancellationLogic } from './runCancellationLogic'
import { runInteractionLogic } from './runInteractionLogic'
import { runStreamLogic } from './runStreamLogic'
import { toolStreamEventsLogic } from './toolStreamEventsLogic'

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
            pushConversationCleared: true,
            respondToPermission: (payload: unknown) => ({ payload }),
            cancelRun: (run?: unknown) => ({ run }),
            markTurnComplete: true,
            setCurrentMode: (mode: string) => ({ mode }),
            handleTerminalStatus: (status: { status: string }) => status,
            setStubStatus: (status: string | null) => ({ status }),
            setStubThinking: (thinking: boolean) => ({ thinking }),
            setStubClearSupported: (supported: boolean) => ({ supported }),
            ingestPermissionRequest: (record: PermissionRequestRecord) => ({ record }),
            markPermissionRequestResolved: (requestId: string) => ({ requestId }),
            deliverPermission: (record: PermissionRequestRecord) => ({ record }),
            permissionResponseFailed: (requestId: string) => ({ requestId }),
            permissionRunChanged: true,
            cancelPermissionDelivery: true,
            clearPermissionRequest: true,
            reset: true,
            appendEntries: true,
            ingestAcpFrame: true,
            closeSse: true,
            bootstrapRun: true,
        }),
        reducers({
            currentRunStatus: [
                'in_progress',
                {
                    setStubStatus: (_: string | null, { status }: { status: string | null }) => status,
                    handleTerminalStatus: (_: string | null, { status }: { status: string }) => status,
                },
            ],
            isThinking: [
                false,
                {
                    setStubThinking: (_: boolean, { thinking }: { thinking: boolean }) => thinking,
                },
            ],
            bootstrappedRunId: [null, {}],
            bootstrappedTaskId: [null, {}],
            log: [{ entries: [], toolUpdateIndex: new Map() }, {}],
            pendingPermissionRequest: [
                null,
                {
                    ingestPermissionRequest: (_: unknown, { record }: { record: PermissionRequestRecord }) => record,
                    markPermissionRequestResolved: (
                        state: PermissionRequestRecord | null,
                        { requestId }: { requestId: string }
                    ) => (state?.requestId === requestId ? null : state),
                    clearPermissionRequest: () => null,
                    permissionRunChanged: () => null,
                    reset: () => null,
                },
            ],
            permissionResponseRequestIds: [
                new Set<string>(),
                {
                    deliverPermission: (_: unknown, { record }: { record: PermissionRequestRecord }) =>
                        new Set([record.requestId]),
                    markPermissionRequestResolved: () => new Set<string>(),
                    permissionResponseFailed: () => new Set<string>(),
                    cancelPermissionDelivery: () => new Set<string>(),
                    reset: () => new Set<string>(),
                },
            ],
            conversationClearSupported: [
                true,
                {
                    setStubClearSupported: (_: boolean, { supported }: { supported: boolean }) => supported,
                },
            ],
            respondingToPermission: [
                false,
                {
                    deliverPermission: () => true,
                    markPermissionRequestResolved: () => false,
                    permissionResponseFailed: () => false,
                    cancelPermissionDelivery: () => false,
                    reset: () => false,
                },
            ],
            currentMode: [
                null,
                {
                    setCurrentMode: (_: string | null, { mode }: { mode: string }) => mode,
                },
            ],
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
    tasksRunsClearConversationCreate: jest.fn(),
    tasksWarmResumeCreate: jest.fn(),
    tasksRunsCancelCreate: jest.fn(),
}))

jest.mock('lib/lemon-ui/LemonToast', () => ({
    lemonToast: { error: jest.fn() },
}))

describe('runInteractionLogic', () => {
    let logic: ReturnType<typeof runInteractionLogic.build>
    let stream: ReturnType<typeof runStreamLogic.build>
    let project: ReturnType<typeof projectLogic.build>
    let toolEvents: ReturnType<typeof toolStreamEventsLogic.build>

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
        ;(tasksRunsCommandCreate as jest.Mock).mockResolvedValue({ jsonrpc: '2.0', result: { queued: true } })
        ;(tasksRunCreate as jest.Mock).mockResolvedValue({ latest_run: { id: 'run-2' } })
        ;(tasksRunsClearConversationCreate as jest.Mock).mockResolvedValue({})
        ;(tasksWarmResumeCreate as jest.Mock).mockResolvedValue({ task_id: TASK_ID, run_id: 'warm-run' })
        initKeaTests()
        project = projectLogic()
        project.mount()
        toolEvents = toolStreamEventsLogic()
        toolEvents.mount()
        toolEvents.actions.registerToolListener('editor', {
            tools: ['create_insight'],
            applyBackTargetId: 'insight-1:activation-1',
            onEvent: jest.fn(),
        })
        stream = runStreamLogic({ streamKey: RUN_ID })
        stream.mount()
        logic = runInteractionLogic({ taskId: TASK_ID, runId: RUN_ID, onRunStarted })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        stream?.unmount()
        project?.unmount()
        toolEvents?.unmount()
    })

    it('adopts the startup draft once and clears it after sending', async () => {
        const onDraftAdopted = jest.fn()
        const attached = runInteractionLogic({
            taskId: TASK_ID,
            runId: 'attached-run',
            initialDraft: 'startup draft',
            onDraftAdopted,
        })
        const unmount = attached.mount()
        try {
            expect(attached.values.composerForm.draft).toBe('startup draft')
            expect(onDraftAdopted).toHaveBeenCalledTimes(1)
            await expectLogic(attached, () => attached.actions.submitComposerForm()).toFinishAllListeners()
            expect(attached.values.composerForm.draft).toBe('')
        } finally {
            unmount()
        }
    })

    it.each(['queue', 'run', 'idle', 'approval'])(
        'routes Escape for %s and preserves the unsent draft',
        async (state) => {
            setThinking(state !== 'idle')
            logic.actions.setComposerFormValues({ draft: 'unsent draft' })
            if (state === 'queue') {
                logic.actions.enqueueMessage('saved message')
            }
            if (state === 'approval') {
                stream.actions.ingestPermissionRequest({
                    requestId: 'approval',
                    sourceRunId: RUN_ID,
                } as PermissionRequestRecord)
            }
            await expectLogic(logic, () => logic.actions.handleEscape()).toFinishAllListeners()
            expect(logic.values.composerForm.draft).toBe('unsent draft')
            expect(logic.values.cancellationState).toBe(['run', 'approval'].includes(state) ? 'waiting' : null)
            if (state === 'queue') {
                expect(tasksRunsCommandCreate).toHaveBeenCalledWith('997', TASK_ID, RUN_ID, {
                    jsonrpc: '2.0',
                    method: 'user_message',
                    params: { content: 'saved message', steer: true },
                })
            } else {
                expect(tasksRunsCommandCreate).not.toHaveBeenCalled()
            }
        }
    )

    it('blocks sends and steering while stopping without clearing either draft or queue', async () => {
        logic.actions.setComposerFormValues({ draft: 'unsent draft' })
        logic.actions.enqueueMessage('saved message')
        runCancellationLogic({ streamKey: RUN_ID }).actions.requestCancellation()
        await expectLogic(logic, () => {
            logic.actions.handleEscape()
            logic.actions.submitComposerForm()
            logic.actions.steerQueue()
            logic.actions.flushQueue()
        }).toFinishAllListeners()
        expect(tasksRunsCommandCreate).not.toHaveBeenCalled()
        expect(logic.values.composerForm.draft).toBe('unsent draft')
        expect(logic.values.queuedMessages).toEqual([{ id: 'queued', content: 'saved message' }])
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
        expect(toolEvents.values.applyBackTargetClaims[RUN_ID]).toEqual([
            { targetId: 'insight-1:activation-1', tools: ['create_insight'] },
        ])
    })

    it('does not send any command when the model or effort is picked', async () => {
        setThinking(false)
        logic.actions.setModel('claude-opus-4-8')
        logic.actions.setEffort('low')

        await expectLogic(logic).toFinishAllListeners()

        // Picking is client-side only now — nothing is synced until the message is sent.
        expect(tasksRunsCommandCreate).not.toHaveBeenCalled()
        expect(logic.values.selectedModel).toBe('claude-opus-4-8')
        expect(logic.values.selectedEffort).toBe('low')
    })

    it('syncs a changed model to the agent right before the message, and only when it changed', async () => {
        setThinking(false)
        logic.actions.setModel('claude-opus-4-8')
        logic.actions.setComposerFormValues({ draft: 'ship it' })

        await expectLogic(logic, () => {
            logic.actions.submitComposerForm()
        }).toFinishAllListeners()

        // The config sync lands before the message, never inside it.
        expect((tasksRunsCommandCreate as jest.Mock).mock.calls).toEqual([
            setConfigCommand('model', 'claude-opus-4-8'),
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

    it('syncs a changed permission mode to the agent right before the message, and only when it changed', async () => {
        setThinking(false)
        // Not `plan` — that's the runtime's default, so it would be no change to sync.
        logic.actions.setMode('bypassPermissions')
        logic.actions.setComposerFormValues({ draft: 'ship it' })

        await expectLogic(logic, () => {
            logic.actions.submitComposerForm()
        }).toFinishAllListeners()

        // The mode sync is a `set_config_option { configId: 'mode' }` command that lands before the message.
        expect((tasksRunsCommandCreate as jest.Mock).mock.calls).toEqual([
            setConfigCommand('mode', 'bypassPermissions'),
            userMessageCommand('ship it'),
        ])

        // A follow-up with the same mode re-syncs nothing — just the message.
        ;(tasksRunsCommandCreate as jest.Mock).mockClear()
        logic.actions.setComposerFormValues({ draft: 'again' })

        await expectLogic(logic, () => {
            logic.actions.submitComposerForm()
        }).toFinishAllListeners()

        expect((tasksRunsCommandCreate as jest.Mock).mock.calls).toEqual([userMessageCommand('again')])
    })

    it('adopts the agent-confirmed mode over a stale manual pick and stays in sync at send time', async () => {
        setThinking(false)
        logic.actions.setMode('plan')
        expect(logic.values.selectedMode).toBe('plan')

        // The agent transitions autonomously (e.g. a plan approval leaves Plan mode) and confirms via a
        // `current_mode_update` frame — the live mode replaces the earlier pick.
        stream.actions.setCurrentMode('auto')
        expect(logic.values.selectedMode).toBe('auto')

        logic.actions.setComposerFormValues({ draft: 'go on' })
        await expectLogic(logic, () => {
            logic.actions.submitComposerForm()
        }).toFinishAllListeners()

        // Already in sync with the agent — only the message goes out, no stale mode re-sync.
        expect((tasksRunsCommandCreate as jest.Mock).mock.calls).toEqual([userMessageCommand('go on')])
    })

    it('seeds the picker from the stored launch mode and coerces the other runtime\u2019s modes', () => {
        // No live `current_mode_update` yet — the run's REST-stored launch mode drives the display.
        logic = runInteractionLogic({ taskId: TASK_ID, runId: RUN_ID, onRunStarted, currentMode: 'plan' })
        expect(logic.values.selectedMode).toBe('plan')

        // A wire mode in the other runtime's vocabulary (a run started from desktop or Slack on Codex)
        // is coerced to this runtime's nearest ceiling rather than shown — or sent — as-is.
        stream.actions.setCurrentMode('full-access')
        expect(logic.values.selectedMode).toBe('bypassPermissions')

        // `acceptEdits` is one of Claude's own modes, so it stays put.
        stream.actions.setCurrentMode('acceptEdits')
        expect(logic.values.selectedMode).toBe('acceptEdits')
    })

    it('seeds a fresh run with the picked permission mode when the run is terminal', async () => {
        setStatus('completed')
        logic.actions.setMode('bypassPermissions')
        logic.actions.setComposerFormValues({ draft: 'continue from here' })

        await expectLogic(logic, () => {
            logic.actions.submitComposerForm()
        }).toFinishAllListeners()

        expect(tasksRunCreate).toHaveBeenCalledWith(
            '997',
            TASK_ID,
            expect.objectContaining({ initial_permission_mode: 'bypassPermissions' }),
            expect.objectContaining({ signal: expect.any(AbortSignal) })
        )
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

    it.each(['approval first', 'turn first'])('holds ordinary delivery until both gates clear: %s', async (order) => {
        const record = { requestId: 'approval-1', sourceRunId: RUN_ID } as PermissionRequestRecord
        stream.actions.ingestPermissionRequest(record)
        setThinking(true)
        logic.actions.setComposerFormValues({ draft: 'follow up' })
        logic.actions.submitComposerForm()
        const resolveApproval = (): void => stream.actions.markPermissionRequestResolved(record.requestId)
        const endTurn = (): void => {
            setThinking(false)
            stream.actions.markTurnComplete()
        }
        const [first, last] = order === 'approval first' ? [resolveApproval, endTurn] : [endTurn, resolveApproval]
        first()
        await expectLogic(logic).toFinishAllListeners()
        expect(tasksRunsCommandCreate).not.toHaveBeenCalled()
        last()
        await expectLogic(logic).toFinishAllListeners()
        expect(tasksRunsCommandCreate).toHaveBeenCalledWith(...userMessageCommand('follow up'))
    })

    it.each(['before approval', 'during confirmation'])(
        'defers Escape steering %s and sends the current saved queue once',
        async (phase) => {
            const record = { requestId: 'approval-1', sourceRunId: RUN_ID } as PermissionRequestRecord
            stream.actions.ingestPermissionRequest(record)
            if (phase === 'during confirmation') {
                stream.actions.deliverPermission(record, 'allow_once')
            }
            setThinking(true)
            logic.actions.enqueueMessage('first')
            logic.actions.setComposerFormValues({ draft: 'still drafting' })
            logic.actions.handleEscape()
            logic.actions.handleEscape()
            logic.actions.enqueueMessage('second')
            expect(logic.values.steerPending).toBe(true)
            expect(tasksRunsCommandCreate).not.toHaveBeenCalled()

            if (phase === 'before approval') {
                stream.actions.deliverPermission(record, 'allow_once')
            }
            expect(tasksRunsCommandCreate).not.toHaveBeenCalled()
            await expectLogic(logic, () =>
                stream.actions.markPermissionRequestResolved(record.requestId)
            ).toFinishAllListeners()
            stream.actions.markPermissionRequestResolved(record.requestId)
            logic.actions.steerQueue()
            expect(tasksRunsCommandCreate).toHaveBeenCalledTimes(1)
            expect(tasksRunsCommandCreate).toHaveBeenCalledWith('997', TASK_ID, RUN_ID, {
                jsonrpc: '2.0',
                method: 'user_message',
                params: { content: 'first\n\nsecond', steer: true },
            })
            expect(logic.values.composerForm.draft).toBe('still drafting')
            expect(logic.values.queuedMessages).toEqual([])
        }
    )

    it.each(['failure', 'replacement approval', 'replacement run', 'terminal', 'cancel', 'reset', 'empty', 'unmount'])(
        'cancels deferred steering on %s',
        async (event) => {
            const record = { requestId: 'approval-1', sourceRunId: RUN_ID } as PermissionRequestRecord
            stream.actions.ingestPermissionRequest(record)
            stream.actions.deliverPermission(record, 'allow_once')
            setThinking(true)
            logic.actions.enqueueMessage('saved')
            logic.actions.steerQueue()
            expect(logic.values.steerPending).toBe(true)

            switch (event) {
                case 'failure':
                    stream.actions.permissionResponseFailed(record.requestId)
                    break
                case 'replacement approval':
                    stream.actions.ingestPermissionRequest({ ...record, requestId: 'approval-2' })
                    break
                case 'replacement run':
                    stream.actions.permissionRunChanged()
                    break
                case 'terminal':
                    setStatus('completed')
                    stream.actions.handleTerminalStatus({ status: 'completed' })
                    break
                case 'cancel':
                    stream.actions.cancelPermissionDelivery()
                    break
                case 'reset':
                    stream.actions.reset()
                    break
                case 'empty':
                    logic.actions.updateQueuedMessage(logic.values.queuedMessages[0].id, '')
                    break
                case 'unmount':
                    logic.unmount()
                    logic.mount()
                    break
            }
            stream.actions.markPermissionRequestResolved(record.requestId)
            await expectLogic(logic).toFinishAllListeners()
            expect(tasksRunsCommandCreate).not.toHaveBeenCalled()
            expect(logic.values.steerPending).toBe(false)
        }
    )

    it.each([
        { jsonrpc: '2.0', error: { code: -32000, message: 'Rejected' } },
        { jsonrpc: '2.0', result: { queued: false } },
        { result: { queued: true } },
        undefined,
    ])('restores unconfirmed steering before newer queued text: %j', async (response) => {
        let complete!: (response: unknown) => void
        ;(tasksRunsCommandCreate as jest.Mock).mockReturnValue(
            new Promise((resolve) => {
                complete = resolve
            })
        )
        setThinking(true)
        logic.actions.enqueueMessage('first')
        logic.actions.setComposerFormValues({ draft: 'unsent draft' })
        logic.actions.steerQueue()
        logic.actions.enqueueMessage('second')
        logic.actions.steerQueue()
        await expectLogic(logic, () => complete(response)).toFinishAllListeners()
        expect(tasksRunsCommandCreate).toHaveBeenCalledTimes(1)
        expect(logic.values.queuedMessages[0].content).toBe('first\n\nsecond')
        expect(logic.values.composerForm.draft).toBe('unsent draft')
        expect(logic.values.steerPending).toBe(false)
        expect(lemonToast.error).toHaveBeenCalled()
        setThinking(false)
        stream.actions.markTurnComplete()
        stream.actions.markPermissionRequestResolved('earlier-approval')
        await expectLogic(logic).toFinishAllListeners()
        expect(tasksRunsCommandCreate).toHaveBeenCalledTimes(1)
    })

    it.each(['reset', 'replacement run', 'cancel', 'terminal', 'unmount'])(
        'ignores a config completion after %s without sending a message',
        async (event) => {
            let complete!: (response: unknown) => void
            ;(tasksRunsCommandCreate as jest.Mock).mockReturnValue(
                new Promise((resolve) => {
                    complete = resolve
                })
            )
            setThinking(true)
            logic.actions.setModel('claude-opus-4-8')
            logic.actions.enqueueMessage('saved')
            logic.actions.steerQueue()
            expect(tasksRunsCommandCreate).toHaveBeenCalledTimes(1)
            switch (event) {
                case 'reset':
                    stream.actions.reset()
                    break
                case 'replacement run':
                    stream.actions.permissionRunChanged()
                    break
                case 'cancel':
                    stream.actions.cancelPermissionDelivery()
                    break
                case 'terminal':
                    setStatus('completed')
                    stream.actions.handleTerminalStatus({ status: 'completed' })
                    break
                case 'unmount':
                    logic.unmount()
                    logic.mount()
                    break
            }
            await expectLogic(logic, () => complete({ jsonrpc: '2.0', result: {} })).toFinishAllListeners()
            expect(tasksRunsCommandCreate).toHaveBeenCalledTimes(1)
        }
    )

    it('does nothing on an empty queue and keeps unsent context after failed steering', async () => {
        setThinking(true)
        const context = attachedContextLogic()
        context.actions.registerContext('test', [{ type: 'insight', key: 'fake', value: 'example insight' }])
        logic.actions.setComposerFormValues({ draft: 'unsent' })
        logic.actions.steerQueue()
        expect(tasksRunsCommandCreate).not.toHaveBeenCalled()
        ;(tasksRunsCommandCreate as jest.Mock).mockRejectedValue(new Error('Connection lost'))
        logic.actions.enqueueMessage('saved')
        await expectLogic(logic, () => logic.actions.steerQueue()).toFinishAllListeners()
        expect(logic.values.pendingContextItems).toHaveLength(1)
        expect(logic.values.composerForm.draft).toBe('unsent')
        expect(logic.values.queuedMessages[0].content).toBe('saved')
        expect(tasksRunsCommandCreate).toHaveBeenCalledTimes(1)
    })

    it.each(['remove', 'edit'])('delivers a fresh queue after discarding a failed submission: %s', async (action) => {
        ;(tasksRunsCommandCreate as jest.Mock).mockRejectedValueOnce(new Error('Connection lost'))
        setThinking(true)
        logic.actions.enqueueMessage('discard this')
        await expectLogic(logic, () => logic.actions.steerQueue()).toFinishAllListeners()
        const { id } = logic.values.queuedMessages[0]
        if (action === 'remove') {
            logic.actions.removeQueuedMessage(id)
        } else {
            logic.actions.updateQueuedMessage(id, '')
        }
        logic.actions.enqueueMessage('new follow-up')
        setThinking(false)
        await expectLogic(logic, () => stream.actions.markTurnComplete()).toFinishAllListeners()
        expect(tasksRunsCommandCreate).toHaveBeenCalledTimes(2)
        expect(tasksRunsCommandCreate).toHaveBeenLastCalledWith(...userMessageCommand('new follow-up'))
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
        expect(toolEvents.values.applyBackTargetClaims[RUN_ID]).toBeUndefined()
    })

    it('starts a fresh run seeded with the message when the run is terminal', async () => {
        setStatus('completed')
        logic.actions.setComposerFormValues({ draft: 'continue from here' })

        await expectLogic(logic, () => {
            logic.actions.submitComposerForm()
        }).toFinishAllListeners()

        // No live-run signal for a finished run — it resumes into a new run instead.
        expect(tasksRunsCommandCreate).not.toHaveBeenCalled()
        expect(tasksRunCreate).toHaveBeenCalledWith(
            '997',
            TASK_ID,
            {
                runtime_adapter: 'claude',
                model: 'claude-sonnet-5',
                reasoning_effort: 'high',
                initial_permission_mode: 'auto',
                resume_from_run_id: RUN_ID,
                pending_user_message: 'continue from here',
            },
            expect.objectContaining({ signal: expect.any(AbortSignal) })
        )
        expect(onRunStarted).toHaveBeenCalledWith('run-2')
        expect(toolEvents.values.applyBackTargetClaims[RUN_ID]).toBeUndefined()
        expect(toolEvents.values.applyBackTargetClaims['run-2']).toEqual([
            { targetId: 'insight-1:activation-1', tools: ['create_insight'] },
        ])
        expect(logic.values.queuedMessages).toEqual([])
        expect(logic.values.composerForm.draft).toBe('')
    })

    it('warms the resumed run while composing and consumes it before submit', async () => {
        jest.useFakeTimers()
        setStatus('cancelled')
        logic.actions.setComposerFormValues({ draft: 'continue from the checkpoint' })
        jest.advanceTimersByTime(300)
        jest.useRealTimers()

        await expectLogic(logic).toFinishAllListeners()
        expect(tasksWarmResumeCreate).toHaveBeenCalledWith('997', TASK_ID, {
            resume_from_run_id: RUN_ID,
            runtime_adapter: 'claude',
            model: 'claude-sonnet-5',
            reasoning_effort: 'high',
            initial_permission_mode: 'auto',
        })

        await expectLogic(logic, () => {
            logic.actions.submitComposerForm()
        }).toFinishAllListeners()

        expect(tasksRunCreate).toHaveBeenCalledWith(
            '997',
            TASK_ID,
            expect.objectContaining({ resume_from_run_id: RUN_ID }),
            expect.objectContaining({ signal: expect.any(AbortSignal) })
        )
    })

    it('records the boundary instead of starting a run when /clear is sent to a terminal run', async () => {
        setStatus('completed')
        logic.actions.setComposerFormValues({ draft: '/clear' })

        await expectLogic(logic, () => {
            logic.actions.submitComposerForm()
        }).toFinishAllListeners()

        // Booting a sandbox would clear a conversation the next run rebuilds from the log anyway.
        expect(tasksRunCreate).not.toHaveBeenCalled()
        expect(tasksRunsClearConversationCreate).toHaveBeenCalledWith('997', TASK_ID, RUN_ID)
        expect(logic.values.composerForm.draft).toBe('')
        // Nothing streams back on a finished run, so the boundary is echoed from here.
        await expectLogic(stream).toDispatchActions([
            (action) => action.type === stream.actionTypes.pushHumanMessage && action.payload.content === '/clear',
            (action) => action.type === stream.actionTypes.pushConversationCleared,
        ])
    })

    it('hands back a warmed successor when /clear succeeds', async () => {
        // The successor booted before the clear boundary was written, so its restored session still
        // holds the conversation /clear promises to remove. Keeping it would let the next message
        // resume the very thing the user just cleared.
        jest.useFakeTimers()
        setStatus('completed')
        logic.actions.setComposerFormValues({ draft: 'keep going' })
        jest.advanceTimersByTime(300)
        jest.useRealTimers()
        await expectLogic(logic).toFinishAllListeners()
        expect(tasksWarmResumeCreate).toHaveBeenCalled()

        logic.actions.setComposerFormValues({ draft: '/clear' })
        await expectLogic(logic, () => {
            logic.actions.submitComposerForm()
        }).toFinishAllListeners()

        expect(tasksRunsClearConversationCreate).toHaveBeenCalled()
        expect(tasksRunsCancelCreate).toHaveBeenCalledWith('997', TASK_ID, 'warm-run', {
            only_if_awaiting_first_message: true,
        })
    })

    it('falls back to a new run when the chain agent cannot honour the clear boundary', async () => {
        // An older agent ignores the marker and resumes the conversation it was meant to retire,
        // so a divider here would claim a clear that never happens.
        ;(stream.actions as unknown as { setStubClearSupported: (s: boolean) => void }).setStubClearSupported(false)
        setStatus('completed')
        logic.actions.setComposerFormValues({ draft: '/clear' })

        await expectLogic(logic, () => {
            logic.actions.submitComposerForm()
        }).toFinishAllListeners()

        expect(tasksRunsClearConversationCreate).not.toHaveBeenCalled()
        expect(tasksRunCreate).toHaveBeenCalled()
    })

    test.each([
        [new Error('boom'), 'Failed to start a new run. Please try again.'],
        [
            new ApiError('starting', 503, undefined, { code: 'warm_run_activation_unavailable' }),
            "Couldn't start this run yet. Please try again.",
        ],
    ])('keeps the draft and unsent context when starting a run fails with %s', async (error, message) => {
        let rejectSend!: (error: unknown) => void
        ;(tasksRunCreate as jest.Mock).mockReturnValueOnce(
            new Promise((_, reject) => {
                rejectSend = reject
            })
        )
        attachedContextLogic().actions.registerContext('scene', [{ type: 'insight', key: 'sig', label: 'Signups' }])
        setStatus('completed')
        logic.actions.setComposerFormValues({ draft: 'continue from here' })
        logic.actions.submitComposerForm()

        expect(logic.values.startingRun).toBe(true)
        expect(logic.values.composerForm.draft).toBe('continue from here')
        expect(attachedContextLogic().values.sentContextKeysByTask[TASK_ID]).toBeUndefined()

        await expectLogic(logic, () => {
            rejectSend(error)
        }).toFinishAllListeners()

        expect(lemonToast.error).toHaveBeenCalledWith(message)
        expect(onRunStarted).not.toHaveBeenCalled()
        expect(logic.values.startingRun).toBe(false)
        expect(logic.values.composerForm.draft).toBe('continue from here')
        expect(logic.values.pendingContextItems).toEqual([{ type: 'insight', key: 'sig', label: 'Signups' }])
        expect(toolEvents.values.applyBackTargetClaims[RUN_ID]).toBeUndefined()

        await expectLogic(logic, () => logic.actions.submitComposerForm()).toFinishAllListeners()

        expect(tasksRunCreate).toHaveBeenCalledTimes(2)
        expect((tasksRunCreate as jest.Mock).mock.calls[1].slice(0, 3)).toEqual(
            (tasksRunCreate as jest.Mock).mock.calls[0].slice(0, 3)
        )
        expect(onRunStarted).toHaveBeenCalledWith('run-2')
        expect(logic.values.composerForm.draft).toBe('')
        expect(logic.values.startingRun).toBe(false)
        expect(attachedContextLogic().values.sentContextKeysByTask[TASK_ID]).toEqual(['insight:sig'])
    })

    test.each(['recovered', 'exhausted', 'timeout', 'unmounted'])(
        'keeps a resumed submission pending through bounded frontend retries: %s',
        async (outcome) => {
            jest.useFakeTimers()
            const error = new ApiError('starting', 503, undefined, {
                code: 'warm_run_activation_unavailable',
                retry_token: 'synthetic-retry-token',
            })
            let rejectFirst!: (error: unknown) => void
            let resolveRetry!: (value: unknown) => void
            let rejectRetry!: (error: unknown) => void
            ;(tasksRunCreate as jest.Mock)
                .mockReturnValueOnce(new Promise((_, reject) => (rejectFirst = reject)))
                .mockRejectedValueOnce(error)
                .mockRejectedValueOnce(error)
                .mockReturnValueOnce(
                    new Promise((resolve, reject) => {
                        resolveRetry = resolve
                        rejectRetry = reject
                    })
                )
            try {
                attachedContextLogic().actions.registerContext('scene', [
                    { type: 'insight', key: 'sig', label: 'Signups' },
                ])
                setStatus('completed')
                logic.actions.setComposerFormValues({ draft: 'continue from here' })
                logic.actions.submitComposerForm()
                await jest.advanceTimersByTimeAsync(10_000)
                rejectFirst(error)
                await jest.advanceTimersByTimeAsync(1750)
                expect(tasksRunCreate).toHaveBeenCalledTimes(4)
                const calls = (tasksRunCreate as jest.Mock).mock.calls
                for (const call of calls.slice(1)) {
                    expect(call.slice(0, 3)).toEqual(calls[0].slice(0, 3))
                    expect(call[3].headers).toEqual({ 'X-PostHog-Warm-Retry': 'synthetic-retry-token' })
                }
                expect(logic.values.startingRun).toBe(true)
                expect(logic.values.composerForm.draft).toBe('continue from here')
                expect(attachedContextLogic().values.sentContextKeysByTask[TASK_ID]).toBeUndefined()
                logic.actions.submitComposerForm()
                expect(tasksRunCreate).toHaveBeenCalledTimes(4)
                if (outcome === 'unmounted') {
                    logic.unmount()
                    resolveRetry({ latest_run: { id: 'warm-run' } })
                    await jest.advanceTimersByTimeAsync(10_000)
                    expect(calls[1][3].signal.aborted).toBe(true)
                    expect(onRunStarted).not.toHaveBeenCalled()
                    return
                }
                await jest.advanceTimersByTimeAsync(8_249)
                expect(logic.values.startingRun).toBe(true)
                await expectLogic(logic, async () => {
                    if (outcome === 'recovered') {
                        resolveRetry({ latest_run: { id: 'warm-run' } })
                    } else if (outcome === 'exhausted') {
                        rejectRetry(
                            new ApiError('starting', 503, undefined, { code: 'warm_run_activation_unavailable' })
                        )
                    } else {
                        await jest.advanceTimersByTimeAsync(1)
                    }
                }).toFinishAllListeners()
                expect(tasksRunCreate).toHaveBeenCalledTimes(4)
                expect(logic.values.startingRun).toBe(false)
                if (outcome === 'recovered') {
                    expect(onRunStarted).toHaveBeenCalledWith('warm-run')
                    expect(logic.values.composerForm.draft).toBe('')
                } else {
                    expect(onRunStarted).not.toHaveBeenCalled()
                    expect(logic.values.composerForm.draft).toBe('continue from here')
                    expect(logic.values.pendingContextItems).toEqual([
                        { type: 'insight', key: 'sig', label: 'Signups' },
                    ])
                    expect(lemonToast.error).toHaveBeenCalledWith("Couldn't start this run yet. Please try again.")
                    resolveRetry({ latest_run: { id: 'late-run' } })
                    await jest.advanceTimersByTimeAsync(0)
                    expect(onRunStarted).not.toHaveBeenCalled()
                }
            } finally {
                jest.useRealTimers()
            }
        }
    )

    it('wraps outgoing content with the attached-context block while echoing the raw text, and dedupes per task', async () => {
        attachedContextLogic().actions.registerContext('scene', [
            { type: 'insight', key: 'sig', label: 'Signups' },
            { type: 'text', value: 'always resend me' },
        ])
        setThinking(false)

        logic.actions.setComposerFormValues({ draft: 'why the drop?' })
        await expectLogic(logic, () => {
            logic.actions.submitComposerForm()
        }).toFinishAllListeners()

        const firstSend = (tasksRunsCommandCreate as jest.Mock).mock.calls[0][3] as {
            params: { content: string }
        }
        // The wire content carries the invisible context block; the echoed human message stays raw.
        expect(firstSend.params.content).toContain('<posthog_untrusted_context>')
        expect(firstSend.params.content).toContain('- insight sig ("Signups")')
        expect(firstSend.params.content.endsWith('why the drop?')).toBe(true)
        await expectLogic(stream).toDispatchActions([
            (action) =>
                action.type === stream.actionTypes.pushHumanMessage && action.payload.content === 'why the drop?',
        ])

        // A second send on the same task must not re-inflate already-sent entity refs — but `text`
        // items are never deduped (repeated text is intentional, mirroring the backend).
        ;(tasksRunsCommandCreate as jest.Mock).mockClear()
        logic.actions.setComposerFormValues({ draft: 'follow up' })
        await expectLogic(logic, () => {
            logic.actions.submitComposerForm()
        }).toFinishAllListeners()

        const secondSend = (tasksRunsCommandCreate as jest.Mock).mock.calls[0][3] as {
            params: { content: string }
        }
        expect(secondSend.params.content).not.toContain('- insight sig')
        expect(secondSend.params.content).toContain('- text: "always resend me"')
        expect(secondSend.params.content.endsWith('follow up')).toBe(true)
    })

    it('prunes context whose rendered line the run log already carries, even with no sent-key bookkeeping', async () => {
        // The reload scenario: `sentContextKeysByTask` is empty (fresh session), but `runStreamLogic`
        // recorded the block lines it found replaying the resume-chain history — the same ref must not
        // be re-wrapped into the next send.
        const seenItem = { type: 'insight', key: 'sig', label: 'Signups' }
        attachedContextLogic().actions.registerContext('scene', [seenItem])
        attachedContextLogic().actions.markContextLinesSeen(TASK_ID, [contextItemLine(seenItem)])
        setThinking(false)

        logic.actions.setComposerFormValues({ draft: 'follow up' })
        await expectLogic(logic, () => {
            logic.actions.submitComposerForm()
        }).toFinishAllListeners()

        const send = (tasksRunsCommandCreate as jest.Mock).mock.calls[0][3] as { params: { content: string } }
        // The only attached item is already in the chain history, so no context block is prepended.
        expect(send.params.content).toBe('follow up')
    })

    it('sends /clear unwrapped so the agent still sees the command at the front, and keeps the context pending', async () => {
        const item = { type: 'insight', key: 'sig', label: 'Signups' }
        attachedContextLogic().actions.registerContext('scene', [item])
        setThinking(false)

        logic.actions.setComposerFormValues({ draft: '/clear' })
        await expectLogic(logic, () => {
            logic.actions.submitComposerForm()
        }).toFinishAllListeners()

        const send = (tasksRunsCommandCreate as jest.Mock).mock.calls[0][3] as { params: { content: string } }
        expect(send.params.content).toBe('/clear')

        // The agent drops the message rather than reading it, so the ref was never really delivered:
        // the next real send must still carry it.
        ;(tasksRunsCommandCreate as jest.Mock).mockClear()
        logic.actions.setComposerFormValues({ draft: 'why the drop?' })
        await expectLogic(logic, () => {
            logic.actions.submitComposerForm()
        }).toFinishAllListeners()

        const next = (tasksRunsCommandCreate as jest.Mock).mock.calls[0][3] as { params: { content: string } }
        expect(next.params.content).toContain('- insight sig ("Signups")')
    })

    it('keeps pruning context sent by a terminal-run send after re-pointing to the fresh run', async () => {
        attachedContextLogic().actions.registerContext('scene', [{ type: 'insight', key: 'sig', label: 'Signups' }])

        // A send on a finished run starts a fresh run, wrapping the pending context into its seed message.
        setStatus('completed')
        logic.actions.setComposerFormValues({ draft: 'continue from here' })
        await expectLogic(logic, () => {
            logic.actions.submitComposerForm()
        }).toFinishAllListeners()

        const createRequest = (tasksRunCreate as jest.Mock).mock.calls[0][2] as { pending_user_message: string }
        expect(createRequest.pending_user_message).toContain('- insight sig ("Signups")')
        expect(onRunStarted).toHaveBeenCalledWith('run-2')

        // The consumer re-points to the new run: a fresh logic instance keyed by the new runId, same task.
        // Sent-context bookkeeping is task-scoped, so the first follow-up must not re-wrap the same ref.
        const nextStream = runStreamLogic({ streamKey: 'run-2' })
        nextStream.mount()
        const nextLogic = runInteractionLogic({ taskId: TASK_ID, runId: 'run-2', onRunStarted })
        nextLogic.mount()
        try {
            nextLogic.actions.setComposerFormValues({ draft: 'follow up' })
            await expectLogic(nextLogic, () => {
                nextLogic.actions.submitComposerForm()
            }).toFinishAllListeners()

            const followUp = (tasksRunsCommandCreate as jest.Mock).mock.calls[0][3] as {
                params: { content: string }
            }
            // The only attached item was already sent this task, so no context block is prepended at all.
            expect(followUp.params.content).toBe('follow up')
        } finally {
            nextLogic.unmount()
            nextStream.unmount()
        }
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
            new Promise((resolve) => {
                resolveSend = () => resolve({ jsonrpc: '2.0', result: { queued: true } })
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
            new Promise((resolve) => {
                resolveSend = () => resolve({ jsonrpc: '2.0', result: { queued: true } })
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

    // The tasks run backend has no server-side consent check, so a follow-up (or a fresh-run send on a
    // terminal run) must be blocked client-side before it reaches `tasksRunsCommandCreate` /
    // `tasksRunCreate`. Uses a distinct `runId` key so the logic is built (and connects to
    // `aiConsentLogic`) after the selector is stubbed.
    it.each(['draft', 'steer'])(
        'blocks %s without consent and never substitutes the unsent draft for steering',
        async (source) => {
            const consent = aiConsentLogic()
            consent.mount()
            const consentAccepted = jest.spyOn(consent.selectors, 'dataProcessingAccepted').mockReturnValue(false)

            const blockedRunId = 'run-blocked'
            const blockedStream = runStreamLogic({ streamKey: blockedRunId })
            blockedStream.mount()
            const blockedLogic = runInteractionLogic({ taskId: TASK_ID, runId: blockedRunId, onRunStarted })
            blockedLogic.mount()

            // Terminal, so typing would otherwise warm a successor — which boots a cloud sandbox and
            // restores the repository snapshot, before the organization has accepted anything.
            ;(blockedStream.actions as unknown as { setStubStatus: (status: string | null) => void }).setStubStatus(
                source === 'draft' ? 'completed' : 'in_progress'
            )
            jest.useFakeTimers()
            blockedLogic.actions.setComposerFormValues({ draft: 'ship it' })
            jest.advanceTimersByTime(300)
            jest.useRealTimers()
            await expectLogic(blockedLogic, () => {
                if (source === 'draft') {
                    blockedLogic.actions.submitComposerForm()
                } else {
                    blockedLogic.actions.enqueueMessage('saved follow up')
                    blockedLogic.actions.steerQueue()
                }
            }).toFinishAllListeners()

            expect(tasksWarmResumeCreate).not.toHaveBeenCalled()
            expect(tasksRunsCommandCreate).not.toHaveBeenCalled()
            expect(tasksRunCreate).not.toHaveBeenCalled()
            expect(blockedLogic.values.consentBlocked).toBe(true)

            if (source === 'steer') {
                consentAccepted.mockReturnValue(true)
                await expectLogic(blockedLogic, () => blockedLogic.actions.submitAfterConsent()).toFinishAllListeners()
                expect(tasksRunsCommandCreate).toHaveBeenCalledWith('997', TASK_ID, blockedRunId, {
                    jsonrpc: '2.0',
                    method: 'user_message',
                    params: { content: 'saved follow up', steer: true },
                })
                expect(blockedLogic.values.composerForm.draft).toBe('ship it')
            }

            blockedLogic.unmount()
            blockedStream.unmount()
            consent.unmount()
            jest.restoreAllMocks()
        }
    )

    it('no-ops on submit with an empty draft', async () => {
        await expectLogic(logic, () => {
            logic.actions.submitComposerForm()
        }).toFinishAllListeners()

        expect(tasksRunsCommandCreate).not.toHaveBeenCalled()
        expect(logic.values.queuedMessages).toEqual([])
    })
})
