import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import type { AcpMessage, PendingPermission, QueuedMessage, SessionConfigOption } from '../conversation/acp-types'
import { buildConversationItems } from '../conversation/buildConversationItems'
import { MethodEnumApi, type ReasoningEffortEnumApi } from '../generated/api.schemas'
import { taskDetailSceneLogic } from '../logics/taskDetailSceneLogic'
import { TaskRun, TaskRunStatus } from '../types'
import { resumeRun, sendRunCommand, uploadRunAttachments, uploadStagedAttachments } from './api'
import { deriveConfigOptions, getConfigOptionByCategory } from './configOptions'
import { derivePendingPermissions } from './permissions'
import type { taskComposerLogicType } from './taskComposerLogicType'

export interface TaskComposerLogicProps {
    taskId: string
}

/** A message held in the client-side queue while the sandbox boots. */
interface LocalQueueItem {
    id: string
    content: string
    files?: File[]
    queuedAt: number
}

const TERMINAL_STATUSES = new Set<TaskRunStatus>([
    TaskRunStatus.COMPLETED,
    TaskRunStatus.FAILED,
    TaskRunStatus.CANCELLED,
])

function newId(prefix: string): string {
    return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}

export const taskComposerLogic = kea<taskComposerLogicType>([
    path(['products', 'tasks', 'composer', 'taskComposerLogic']),
    props({} as TaskComposerLogicProps),
    key((props) => props.taskId),

    connect((props: TaskComposerLogicProps) => ({
        values: [
            taskDetailSceneLogic(props),
            ['events', 'selectedRun', 'selectedRunId'],
            teamLogic,
            ['currentProjectId'],
        ],
        actions: [taskDetailSceneLogic(props), ['loadSelectedRun', 'loadRuns', 'setSelectedRunId']],
    })),

    actions({
        setDraft: (draft: string) => ({ draft }),
        clearDraft: true,
        addFiles: (files: File[]) => ({ files }),
        removeFile: (index: number) => ({ index }),
        clearFiles: true,
        sendMessage: true,
        resumeRun: (message: string, files: File[]) => ({ message, files }),
        cancelRun: true,
        flushQueue: true,
        setSending: (sending: boolean) => ({ sending }),
        setConfigOption: (configId: string, value: string) => ({ configId, value }),
        rollbackConfigOption: (configId: string, value: string) => ({ configId, value }),
        respondToPermission: (
            requestId: string,
            optionId: string,
            customInput?: string,
            answers?: Record<string, string>
        ) => ({ requestId, optionId, customInput, answers }),
        unresolvePermission: (requestId: string) => ({ requestId }),
        enqueueLocal: (message: LocalQueueItem) => ({ message }),
        clearLocalQueue: true,
        appendOptimistic: (content: string) => ({ content }),
        clearOptimistic: true,
    }),

    reducers({
        draft: [
            '' as string,
            {
                setDraft: (_, { draft }) => draft,
                clearDraft: () => '',
            },
        ],
        pendingFiles: [
            [] as File[],
            {
                addFiles: (state, { files }) => [...state, ...files],
                removeFile: (state, { index }) => state.filter((_, i) => i !== index),
                clearFiles: () => [],
            },
        ],
        localQueue: [
            [] as LocalQueueItem[],
            {
                enqueueLocal: (state, { message }) => [...state, message],
                clearLocalQueue: () => [],
                // Switching runs must not leak a queue onto a different run.
                setSelectedRunId: () => [],
            },
        ],
        optimisticUserMessages: [
            [] as { id: string; content: string; timestamp: number }[],
            {
                appendOptimistic: (state, { content }) => [
                    ...state,
                    { id: newId('optimistic'), content, timestamp: Date.now() },
                ],
                clearOptimistic: () => [],
                setSelectedRunId: () => [],
            },
        ],
        configOverrides: [
            {} as Record<string, string>,
            {
                setConfigOption: (state, { configId, value }) => ({ ...state, [configId]: value }),
                // Only roll back if our value is still the active override — a newer
                // change to the same option must not be clobbered by a stale failure.
                rollbackConfigOption: (state, { configId, value }) => {
                    if (state[configId] !== value) {
                        return state
                    }
                    const next = { ...state }
                    delete next[configId]
                    return next
                },
                setSelectedRunId: () => ({}),
            },
        ],
        resolvedPermissionIds: [
            {} as Record<string, true>,
            {
                respondToPermission: (state, { requestId }) => ({ ...state, [requestId]: true }),
                unresolvePermission: (state, { requestId }) => {
                    const next = { ...state }
                    delete next[requestId]
                    return next
                },
                setSelectedRunId: () => ({}),
            },
        ],
        sending: [
            false,
            {
                setSending: (_, { sending }) => sending,
                setSelectedRunId: () => false,
            },
        ],
    }),

    selectors({
        taskId: [() => [(_, props) => props.taskId], (taskId) => taskId],
        runStatus: [(s) => [s.selectedRun], (run: TaskRun | null) => run?.status ?? null],
        isRunning: [
            (s) => [s.runStatus],
            (status): boolean => status === TaskRunStatus.QUEUED || status === TaskRunStatus.IN_PROGRESS,
        ],
        isTerminal: [(s) => [s.runStatus], (status): boolean => !!status && TERMINAL_STATUSES.has(status)],
        sandboxReady: [(s) => [s.runStatus], (status): boolean => status === TaskRunStatus.IN_PROGRESS],
        queuedMessages: [
            (s) => [s.localQueue],
            (localQueue): QueuedMessage[] =>
                localQueue.map((item) => ({ id: item.id, content: item.content, queuedAt: item.queuedAt })),
        ],
        // Build the conversation once per event batch; downstream selectors (turn
        // completion, optimistic dedupe, item count) all read from this single pass.
        conversationBuild: [
            (s) => [s.events],
            (events: AcpMessage[]): ReturnType<typeof buildConversationItems> => buildConversationItems(events, null),
        ],
        itemCount: [(s) => [s.conversationBuild], (build): number => build.items.length],
        lastTurnComplete: [(s) => [s.conversationBuild], (build): boolean => build.lastTurnInfo?.isComplete ?? false],
        agentBusy: [
            (s) => [s.isRunning, s.lastTurnComplete],
            (isRunning, lastTurnComplete): boolean => isRunning && !lastTurnComplete,
        ],
        configOptions: [
            (s) => [s.events, s.configOverrides],
            (events: AcpMessage[], overrides): SessionConfigOption[] => {
                const derived = deriveConfigOptions(events)
                if (Object.keys(overrides).length === 0) {
                    return derived
                }
                return derived.map((opt) =>
                    opt.type === 'select' && overrides[opt.id] !== undefined
                        ? { ...opt, currentValue: overrides[opt.id] }
                        : opt
                )
            },
        ],
        pendingPermissions: [
            (s) => [s.events, s.resolvedPermissionIds],
            (events: AcpMessage[], resolved): PendingPermission[] =>
                derivePendingPermissions(events).filter((permission) => !resolved[permission.requestId]),
        ],
        firstPendingPermission: [
            (s) => [s.pendingPermissions],
            (permissions): PendingPermission | null => permissions[0] ?? null,
        ],
        visibleOptimisticItems: [
            (s) => [s.optimisticUserMessages, s.conversationBuild],
            (optimistic, build): { id: string; content: string; timestamp: number }[] => {
                if (optimistic.length === 0) {
                    return []
                }
                const userContents = new Set(
                    build.items
                        .filter((item) => item.type === 'user_message')
                        .map((item) => (item as { content: string }).content.trim())
                )
                return optimistic.filter((item) => !userContents.has(item.content.trim()))
            },
        ],
    }),

    listeners(({ values, actions, props }) => ({
        sendMessage: async () => {
            if (values.sending) {
                return
            }
            const text = values.draft.trim()
            const files = values.pendingFiles
            if (!text && files.length === 0) {
                return
            }
            const runId = values.selectedRunId
            const projectId = values.currentProjectId
            if (!runId || !projectId) {
                return
            }

            actions.clearDraft()
            actions.clearFiles()

            // Terminal run: the sandbox is gone, so a follow-up resumes the task
            // by spinning a new run that carries the conversation history.
            if (values.isTerminal) {
                actions.resumeRun(text, files)
                return
            }

            // Sandbox not ready yet: hold the message client-side and flush it
            // once the run flips to in_progress. Carry the files along so they
            // aren't lost while the run boots.
            if (!values.sandboxReady) {
                actions.enqueueLocal({ id: newId('queue'), content: text, files, queuedAt: Date.now() })
                return
            }

            actions.appendOptimistic(text)
            actions.setSending(true)
            try {
                const artifactIds = await uploadRunAttachments(String(projectId), props.taskId, runId, files)
                const params: Record<string, unknown> = {}
                if (text) {
                    params.content = text
                }
                if (artifactIds.length > 0) {
                    params.artifact_ids = artifactIds
                }
                await sendRunCommand(String(projectId), props.taskId, runId, MethodEnumApi.UserMessage, params)
                actions.loadSelectedRun()
            } catch (error) {
                actions.clearOptimistic()
                // Restore the user's input so nothing is silently lost on failure.
                actions.setDraft(text)
                if (files.length > 0) {
                    actions.addFiles(files)
                }
                lemonToast.error(`Failed to send message: ${(error as Error).message}`)
            } finally {
                actions.setSending(false)
            }
        },

        flushQueue: async () => {
            // Guard against overlapping flushes (e.g. status flapping re-firing the
            // sandboxReady subscription while a flush is still in flight).
            if (values.sending || !values.sandboxReady || values.localQueue.length === 0) {
                return
            }
            const runId = values.selectedRunId
            const projectId = values.currentProjectId
            if (!runId || !projectId) {
                return
            }
            const queued = values.localQueue
            const combined = queued.map((message) => message.content).join('\n\n')
            const files = queued.flatMap((message) => message.files ?? [])
            actions.clearLocalQueue()
            actions.appendOptimistic(combined)
            actions.setSending(true)
            try {
                const artifactIds = await uploadRunAttachments(String(projectId), props.taskId, runId, files)
                const params: Record<string, unknown> = { content: combined }
                if (artifactIds.length > 0) {
                    params.artifact_ids = artifactIds
                }
                await sendRunCommand(String(projectId), props.taskId, runId, MethodEnumApi.UserMessage, params)
                actions.loadSelectedRun()
            } catch (error) {
                actions.clearOptimistic()
                // Don't lose the message — put it back on the queue for a later retry.
                actions.enqueueLocal({ id: newId('queue'), content: combined, files, queuedAt: Date.now() })
                lemonToast.error(`Failed to send queued message: ${(error as Error).message}`)
            } finally {
                actions.setSending(false)
            }
        },

        resumeRun: async ({ message, files }) => {
            if (values.sending) {
                return
            }
            const previousRunId = values.selectedRunId
            const projectId = values.currentProjectId
            if (!previousRunId || !projectId) {
                return
            }
            const modelOption = getConfigOptionByCategory(values.configOptions, 'model')
            const thoughtOption = getConfigOptionByCategory(values.configOptions, 'thought_level')
            const stateModel = (values.selectedRun?.state as { model?: string } | undefined)?.model
            const model = (modelOption?.type === 'select' ? modelOption.currentValue : undefined) ?? stateModel
            const reasoning = thoughtOption?.type === 'select' ? thoughtOption.currentValue : undefined

            actions.appendOptimistic(message)
            actions.setSending(true)
            try {
                const artifactIds = await uploadStagedAttachments(String(projectId), props.taskId, files)
                const newRunId = await resumeRun(String(projectId), props.taskId, {
                    resumeFromRunId: previousRunId,
                    message,
                    artifactIds,
                    model,
                    branch: values.selectedRun?.branch ?? null,
                    reasoningEffort: reasoning as ReasoningEffortEnumApi | undefined,
                })
                if (!newRunId) {
                    throw new Error('The server did not return a new run')
                }
                actions.clearOptimistic()
                actions.loadRuns()
                actions.setSelectedRunId(newRunId, props.taskId)
            } catch (error) {
                actions.clearOptimistic()
                // Restore the user's input so the follow-up isn't lost on failure.
                actions.setDraft(message)
                if (files.length > 0) {
                    actions.addFiles(files)
                }
                lemonToast.error(`Failed to continue this task: ${(error as Error).message}`)
            } finally {
                actions.setSending(false)
            }
        },

        cancelRun: async () => {
            const runId = values.selectedRunId
            const projectId = values.currentProjectId
            if (!runId || !projectId) {
                return
            }
            try {
                await sendRunCommand(String(projectId), props.taskId, runId, MethodEnumApi.Cancel, {})
                actions.loadSelectedRun()
            } catch (error) {
                lemonToast.error(`Failed to stop: ${(error as Error).message}`)
            }
        },

        setConfigOption: async ({ configId, value }) => {
            const runId = values.selectedRunId
            const projectId = values.currentProjectId
            if (!runId || !projectId) {
                return
            }
            try {
                await sendRunCommand(String(projectId), props.taskId, runId, MethodEnumApi.SetConfigOption, {
                    configId,
                    value,
                })
            } catch (error) {
                actions.rollbackConfigOption(configId, value)
                lemonToast.error(`Failed to update setting: ${(error as Error).message}`)
            }
        },

        respondToPermission: async ({ requestId, optionId, customInput, answers }) => {
            const runId = values.selectedRunId
            const projectId = values.currentProjectId
            if (!runId || !projectId) {
                return
            }
            const params: Record<string, unknown> = { requestId, optionId }
            if (customInput) {
                params.customInput = customInput
            }
            if (answers) {
                params.answers = answers
            }
            try {
                await sendRunCommand(String(projectId), props.taskId, runId, MethodEnumApi.PermissionResponse, params)
                actions.loadSelectedRun()
            } catch (error) {
                actions.unresolvePermission(requestId)
                lemonToast.error(`Failed to respond: ${(error as Error).message}`)
            }
        },
    })),

    subscriptions(({ actions }) => ({
        sandboxReady: (ready: boolean) => {
            if (ready) {
                actions.flushQueue()
            }
        },
    })),
])
