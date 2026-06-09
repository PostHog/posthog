import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'

import type { AcpMessage } from '../conversation/acp-types'
import { MethodEnumApi } from '../generated/api.schemas'
import { taskDetailSceneLogic } from '../logics/taskDetailSceneLogic'
import { TaskRun, TaskRunEnvironment, TaskRunStatus } from '../types'
import { resumeRun, sendRunCommand, uploadRunAttachments, uploadStagedAttachments } from './api'
import { taskComposerLogic } from './taskComposerLogic'

jest.mock('./api', () => ({
    sendRunCommand: jest.fn(),
    uploadRunAttachments: jest.fn(),
    uploadStagedAttachments: jest.fn(),
    resumeRun: jest.fn(),
}))

const mockSendRunCommand = sendRunCommand as jest.MockedFunction<typeof sendRunCommand>
const mockUploadRunAttachments = uploadRunAttachments as jest.MockedFunction<typeof uploadRunAttachments>
const mockUploadStagedAttachments = uploadStagedAttachments as jest.MockedFunction<typeof uploadStagedAttachments>
const mockResumeRun = resumeRun as jest.MockedFunction<typeof resumeRun>

const TASK_ID = 'task-123'
const RUN_ID = 'run-1'
const PROJECT_ID = '997'

function createMockRun(status: TaskRunStatus): TaskRun {
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

function configOptionEvent(configId: string, currentValue: string, ts = 1): AcpMessage {
    return {
        type: 'acp_message',
        ts,
        message: {
            jsonrpc: '2.0',
            method: 'session/update',
            params: {
                update: {
                    sessionUpdate: 'config_option_update',
                    configOptions: [
                        {
                            id: configId,
                            name: 'Model',
                            type: 'select',
                            currentValue,
                            options: [
                                { value: 'a', name: 'A' },
                                { value: 'b', name: 'B' },
                            ],
                        },
                    ],
                },
            },
        },
    }
}

function permissionRequestEvent(requestId: string, ts = 1): AcpMessage {
    return {
        type: 'acp_message',
        ts,
        message: {
            jsonrpc: '2.0',
            method: '_posthog/permission_request',
            params: {
                requestId,
                toolCall: { toolCallId: `tc-${requestId}`, title: 'Run command', kind: 'execute' },
                options: [
                    { optionId: 'allow_once', name: 'Allow', kind: 'allow_once' },
                    { optionId: 'reject_once', name: 'Reject', kind: 'reject_once' },
                ],
            },
        },
    }
}

function createJsonResponse(payload: unknown): Response {
    return new Response(JSON.stringify(payload), { headers: { 'Content-Type': 'application/json' } })
}

function createDetailFetchMock(run: TaskRun): typeof fetch {
    return jest.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (/\/tasks\/[^/]+\/runs\/[^/]+\/logs\/$/.test(url)) {
            return Promise.resolve(new Response(''))
        }
        if (/\/tasks\/[^/]+\/runs\/[^/]+\/$/.test(url)) {
            return Promise.resolve(createJsonResponse(run))
        }
        if (/\/tasks\/[^/]+\/runs\/$/.test(url)) {
            return Promise.resolve(createJsonResponse({ results: [] }))
        }
        if (/\/tasks\/[^/]+\/$/.test(url)) {
            return Promise.resolve(createJsonResponse({ id: TASK_ID }))
        }
        return Promise.resolve(new Response(''))
    }) as typeof fetch
}

describe('taskComposerLogic', () => {
    const originalFetch = global.fetch
    let logic: ReturnType<typeof taskComposerLogic.build>
    let detailLogic: ReturnType<typeof taskDetailSceneLogic.build>

    async function mountWithRun(status: TaskRunStatus, events: AcpMessage[] = []): Promise<void> {
        global.fetch = createDetailFetchMock(createMockRun(status))
        detailLogic = taskDetailSceneLogic({ taskId: TASK_ID })
        detailLogic.mount()
        await expectLogic(detailLogic).toFinishAllListeners()

        detailLogic.actions.setSelectedRunId(RUN_ID, TASK_ID)
        await expectLogic(detailLogic).toFinishAllListeners()
        detailLogic.actions.loadSelectedRunSuccess(createMockRun(status))
        if (events.length > 0) {
            detailLogic.actions.appendStreamEvents(events)
        }
        await expectLogic(detailLogic).toFinishAllListeners()

        logic = taskComposerLogic({ taskId: TASK_ID })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        initKeaTests()
        mockSendRunCommand.mockReset()
        mockUploadRunAttachments.mockReset()
        mockSendRunCommand.mockResolvedValue(undefined)
        mockUploadRunAttachments.mockResolvedValue([])
        mockUploadStagedAttachments.mockReset()
        mockUploadStagedAttachments.mockResolvedValue([])
        mockResumeRun.mockReset()
        mockResumeRun.mockResolvedValue('run-2')
        jest.spyOn(lemonToast, 'error').mockReturnValue('' as any)
    })

    afterEach(() => {
        logic?.unmount()
        detailLogic?.unmount()
        jest.restoreAllMocks()
        global.fetch = originalFetch
    })

    it('sandboxReady reflects in_progress status', async () => {
        await mountWithRun(TaskRunStatus.IN_PROGRESS)
        expect(logic.values.sandboxReady).toBe(true)
    })

    it('sends a user_message command with content when sandbox is ready', async () => {
        await mountWithRun(TaskRunStatus.IN_PROGRESS)
        logic.actions.setDraft('hello world')
        logic.actions.sendMessage()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockSendRunCommand).toHaveBeenCalledWith(PROJECT_ID, TASK_ID, RUN_ID, MethodEnumApi.UserMessage, {
            content: 'hello world',
        })
        expect(logic.values.draft).toBe('')
    })

    it('includes artifact_ids when attachments upload', async () => {
        mockUploadRunAttachments.mockResolvedValue(['artifact-a', 'artifact-b'])
        await mountWithRun(TaskRunStatus.IN_PROGRESS)
        logic.actions.setDraft('with files')
        logic.actions.addFiles([new File(['x'], 'a.txt')])
        logic.actions.sendMessage()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockSendRunCommand).toHaveBeenCalledWith(PROJECT_ID, TASK_ID, RUN_ID, MethodEnumApi.UserMessage, {
            content: 'with files',
            artifact_ids: ['artifact-a', 'artifact-b'],
        })
    })

    it('does nothing when draft is empty and no files are attached', async () => {
        await mountWithRun(TaskRunStatus.IN_PROGRESS)
        logic.actions.setDraft('   ')
        logic.actions.sendMessage()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockSendRunCommand).not.toHaveBeenCalled()
    })

    it('appends an optimistic user message before the round-trip', async () => {
        await mountWithRun(TaskRunStatus.IN_PROGRESS)
        logic.actions.setDraft('optimistic message')
        logic.actions.sendMessage()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.optimisticUserMessages.map((m) => m.content)).toContain('optimistic message')
        expect(logic.values.visibleOptimisticItems.map((m) => m.content)).toContain('optimistic message')
    })

    it('rolls back the optimistic message and restores the draft when send fails', async () => {
        mockSendRunCommand.mockRejectedValueOnce(new Error('boom'))
        await mountWithRun(TaskRunStatus.IN_PROGRESS)
        logic.actions.setDraft('will fail')
        logic.actions.sendMessage()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.optimisticUserMessages).toHaveLength(0)
        expect(logic.values.draft).toBe('will fail')
        expect(lemonToast.error).toHaveBeenCalled()
    })

    it('queues the message locally while the sandbox is not ready', async () => {
        await mountWithRun(TaskRunStatus.QUEUED)
        expect(logic.values.sandboxReady).toBe(false)

        logic.actions.setDraft('queued while booting')
        logic.actions.sendMessage()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockSendRunCommand).not.toHaveBeenCalled()
        expect(logic.values.localQueue.map((m) => m.content)).toEqual(['queued while booting'])
        expect(logic.values.draft).toBe('')
    })

    it('flushes the local queue when the run flips to in_progress', async () => {
        await mountWithRun(TaskRunStatus.QUEUED)
        logic.actions.enqueueLocal({ id: 'q1', content: 'first', queuedAt: 1 })
        logic.actions.enqueueLocal({ id: 'q2', content: 'second', queuedAt: 2 })
        await expectLogic(logic).toFinishAllListeners()

        detailLogic.actions.loadSelectedRunSuccess(createMockRun(TaskRunStatus.IN_PROGRESS))
        await expectLogic(logic).toFinishAllListeners()

        expect(mockSendRunCommand).toHaveBeenCalledWith(PROJECT_ID, TASK_ID, RUN_ID, MethodEnumApi.UserMessage, {
            content: 'first\n\nsecond',
        })
        expect(logic.values.localQueue).toHaveLength(0)
    })

    it('flushQueue does nothing when the queue is empty', async () => {
        await mountWithRun(TaskRunStatus.IN_PROGRESS)
        logic.actions.flushQueue()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockSendRunCommand).not.toHaveBeenCalled()
    })

    it('re-enqueues the message and toasts when flushQueue fails', async () => {
        mockSendRunCommand.mockRejectedValueOnce(new Error('flush failed'))
        await mountWithRun(TaskRunStatus.QUEUED)
        logic.actions.enqueueLocal({ id: 'q1', content: 'lost', queuedAt: 1 })
        await expectLogic(logic).toFinishAllListeners()

        detailLogic.actions.loadSelectedRunSuccess(createMockRun(TaskRunStatus.IN_PROGRESS))
        await expectLogic(logic).toFinishAllListeners()

        // The failed send must not lose the user's message — it goes back on the queue.
        expect(logic.values.localQueue.map((m) => m.content)).toEqual(['lost'])
        expect(lemonToast.error).toHaveBeenCalled()
    })

    it('sends a cancel command and reloads the run', async () => {
        await mountWithRun(TaskRunStatus.IN_PROGRESS)
        logic.actions.cancelRun()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockSendRunCommand).toHaveBeenCalledWith(PROJECT_ID, TASK_ID, RUN_ID, MethodEnumApi.Cancel, {})
    })

    it('surfaces a toast when cancel fails', async () => {
        mockSendRunCommand.mockRejectedValueOnce(new Error('cannot stop'))
        await mountWithRun(TaskRunStatus.IN_PROGRESS)
        logic.actions.cancelRun()
        await expectLogic(logic).toFinishAllListeners()

        expect(lemonToast.error).toHaveBeenCalled()
    })

    it('optimistically applies a config override and sends set_config_option', async () => {
        await mountWithRun(TaskRunStatus.IN_PROGRESS, [configOptionEvent('model', 'a')])
        logic.actions.setConfigOption('model', 'b')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.configOverrides).toEqual({ model: 'b' })
        const modelOption = logic.values.configOptions.find((opt) => opt.id === 'model')
        expect(modelOption?.currentValue).toBe('b')
        expect(mockSendRunCommand).toHaveBeenCalledWith(PROJECT_ID, TASK_ID, RUN_ID, MethodEnumApi.SetConfigOption, {
            configId: 'model',
            value: 'b',
        })
    })

    it('rolls back the config override when set_config_option fails', async () => {
        mockSendRunCommand.mockRejectedValueOnce(new Error('config error'))
        await mountWithRun(TaskRunStatus.IN_PROGRESS, [configOptionEvent('model', 'a')])
        logic.actions.setConfigOption('model', 'b')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.configOverrides).toEqual({})
        const modelOption = logic.values.configOptions.find((opt) => opt.id === 'model')
        expect(modelOption?.currentValue).toBe('a')
        expect(lemonToast.error).toHaveBeenCalled()
    })

    it('responds to a permission and marks it resolved', async () => {
        await mountWithRun(TaskRunStatus.IN_PROGRESS, [permissionRequestEvent('req-1')])
        expect(logic.values.pendingPermissions.map((p) => p.requestId)).toEqual(['req-1'])

        logic.actions.respondToPermission('req-1', 'allow_once')
        await expectLogic(logic).toFinishAllListeners()

        expect(mockSendRunCommand).toHaveBeenCalledWith(PROJECT_ID, TASK_ID, RUN_ID, MethodEnumApi.PermissionResponse, {
            requestId: 'req-1',
            optionId: 'allow_once',
        })
        expect(logic.values.pendingPermissions).toHaveLength(0)
    })

    it('includes customInput and answers in the permission_response params', async () => {
        await mountWithRun(TaskRunStatus.IN_PROGRESS, [permissionRequestEvent('req-2')])
        logic.actions.respondToPermission('req-2', 'allow_once', 'extra', { q1: 'a1' })
        await expectLogic(logic).toFinishAllListeners()

        expect(mockSendRunCommand).toHaveBeenCalledWith(PROJECT_ID, TASK_ID, RUN_ID, MethodEnumApi.PermissionResponse, {
            requestId: 'req-2',
            optionId: 'allow_once',
            customInput: 'extra',
            answers: { q1: 'a1' },
        })
    })

    it('unresolves the permission and re-surfaces it when the response fails', async () => {
        mockSendRunCommand.mockRejectedValueOnce(new Error('respond failed'))
        await mountWithRun(TaskRunStatus.IN_PROGRESS, [permissionRequestEvent('req-3')])
        logic.actions.respondToPermission('req-3', 'allow_once')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.pendingPermissions.map((p) => p.requestId)).toEqual(['req-3'])
        expect(lemonToast.error).toHaveBeenCalled()
    })

    it('resumes a terminal run by creating a follow-up run and selecting it', async () => {
        await mountWithRun(TaskRunStatus.COMPLETED)
        logic.actions.setDraft('keep going')
        logic.actions.sendMessage()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockSendRunCommand).not.toHaveBeenCalled()
        expect(mockResumeRun).toHaveBeenCalledWith(
            PROJECT_ID,
            TASK_ID,
            expect.objectContaining({ resumeFromRunId: RUN_ID, message: 'keep going' })
        )
        expect(detailLogic.values.selectedRunId).toBe('run-2')
    })

    it('uploads staged attachments before resuming', async () => {
        mockUploadStagedAttachments.mockResolvedValue(['staged-1'])
        await mountWithRun(TaskRunStatus.FAILED)
        logic.actions.setDraft('resume with file')
        logic.actions.addFiles([new File(['x'], 'a.txt')])
        logic.actions.sendMessage()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockUploadStagedAttachments).toHaveBeenCalled()
        expect(mockResumeRun).toHaveBeenCalledWith(
            PROJECT_ID,
            TASK_ID,
            expect.objectContaining({ artifactIds: ['staged-1'], message: 'resume with file' })
        )
    })

    it('exposes queuedMessages derived from the local queue', async () => {
        await mountWithRun(TaskRunStatus.QUEUED)
        logic.actions.enqueueLocal({ id: 'q1', content: 'hello', queuedAt: 5 })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.queuedMessages).toEqual([{ id: 'q1', content: 'hello', queuedAt: 5 }])
    })

    it('toggles the sending flag around an in-flight send and ignores re-entrant sends', async () => {
        let resolveSend: () => void = () => {}
        mockSendRunCommand.mockImplementationOnce(
            () => new Promise<undefined>((resolve) => (resolveSend = () => resolve(undefined)))
        )
        await mountWithRun(TaskRunStatus.IN_PROGRESS)
        logic.actions.setDraft('first')
        logic.actions.sendMessage()
        await expectLogic(logic).toMatchValues({ sending: true })

        // A re-entrant send while one is in flight must not fire a second command.
        logic.actions.setDraft('second')
        logic.actions.sendMessage()
        expect(mockSendRunCommand).toHaveBeenCalledTimes(1)

        resolveSend()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.sending).toBe(false)
    })

    it('restores the draft and attachments when a send fails', async () => {
        mockSendRunCommand.mockRejectedValueOnce(new Error('nope'))
        await mountWithRun(TaskRunStatus.IN_PROGRESS)
        logic.actions.setDraft('keep me')
        logic.actions.addFiles([new File(['x'], 'a.txt')])
        logic.actions.sendMessage()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.draft).toBe('keep me')
        expect(logic.values.pendingFiles).toHaveLength(1)
        expect(logic.values.sending).toBe(false)
    })

    it('does not clobber a newer config change when an older one fails', async () => {
        // First command (x) fails; the second (y) succeeds.
        mockSendRunCommand.mockRejectedValueOnce(new Error('slow fail'))
        await mountWithRun(TaskRunStatus.IN_PROGRESS, [configOptionEvent('model', 'a')])
        logic.actions.setConfigOption('model', 'x')
        logic.actions.setConfigOption('model', 'y')
        await expectLogic(logic).toFinishAllListeners()

        // The stale rollback for 'x' must not revert the newer 'y' override.
        expect(logic.values.configOverrides).toEqual({ model: 'y' })
    })

    it('clears per-run composer state when the selected run changes', async () => {
        await mountWithRun(TaskRunStatus.QUEUED)
        logic.actions.enqueueLocal({ id: 'q1', content: 'stale', queuedAt: 1 })
        logic.actions.appendOptimistic('stale-optimistic')
        await expectLogic(logic).toFinishAllListeners()

        detailLogic.actions.setSelectedRunId('run-9', TASK_ID)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.localQueue).toHaveLength(0)
        expect(logic.values.optimisticUserMessages).toHaveLength(0)
        expect(logic.values.configOverrides).toEqual({})
    })

    it('surfaces an error and stays on the old run when resume returns no run id', async () => {
        mockResumeRun.mockResolvedValue(null)
        await mountWithRun(TaskRunStatus.COMPLETED)
        logic.actions.setDraft('continue please')
        logic.actions.sendMessage()
        await expectLogic(logic).toFinishAllListeners()

        expect(lemonToast.error).toHaveBeenCalled()
        expect(logic.values.draft).toBe('continue please')
        expect(detailLogic.values.selectedRunId).toBe(RUN_ID)
    })

    it('does not send commands when no run is selected', async () => {
        global.fetch = createDetailFetchMock(createMockRun(TaskRunStatus.IN_PROGRESS))
        detailLogic = taskDetailSceneLogic({ taskId: TASK_ID })
        detailLogic.mount()
        await expectLogic(detailLogic).toFinishAllListeners()

        logic = taskComposerLogic({ taskId: TASK_ID })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.cancelRun()
        logic.actions.setConfigOption('model', 'b')
        logic.actions.respondToPermission('req', 'allow_once')
        await expectLogic(logic).toFinishAllListeners()

        expect(mockSendRunCommand).not.toHaveBeenCalled()
    })
})
