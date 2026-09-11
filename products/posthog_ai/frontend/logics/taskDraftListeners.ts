import type { ListenerDefinitions } from 'kea'

import type { runInteractionLogicType } from './runInteractionLogic'
import { TaskDraftPersistence, type TaskDraftState, taskDraftStorageKey } from './taskDraftPersistence'

export function taskDraftState(logic: runInteractionLogicType): TaskDraftState {
    return {
        runId: logic.props.runId,
        draft: logic.values.composerForm.draft,
        queuedText: logic.values.queuedMessages.map((message) => message.content).join('\n\n'),
        recovery: logic.values.draftRecovery,
    }
}

export function taskDraftListeners(logic: runInteractionLogicType): ListenerDefinitions<runInteractionLogicType> {
    const { actions, cache } = logic
    const save = (): void => {
        if (!cache.restoringTaskDraft) {
            const persistence: TaskDraftPersistence | undefined = cache.taskDraftPersistence
            persistence?.save(taskDraftState(logic))
        }
    }

    return {
        enableTaskDraftPersistence: ({ userId, projectId }: { userId: string; projectId: number }): void => {
            const previous: { userId: string; projectId: number } | undefined = cache.taskDraftIdentity
            if (previous && (previous.userId !== userId || previous.projectId !== projectId)) {
                cache.restoringTaskDraft = true
                cache.taskDraftPersistence = undefined
                actions.clearQueue()
                actions.resetComposerForm()
                cache.restoringTaskDraft = false
            }
            cache.taskDraftIdentity = { userId, projectId }
            actions.hydrateTaskDraft()
        },
        hydrateTaskDraft: ({ taskId }: { taskId?: string }): void => {
            if (taskId) {
                cache.taskDraftTaskId = taskId
            }
            const identity: { userId: string; projectId: number } | undefined = cache.taskDraftIdentity
            const savedTaskId = logic.props.taskId || cache.taskDraftTaskId
            if (!identity || !savedTaskId) {
                return
            }
            const key = taskDraftStorageKey(identity.userId, identity.projectId, savedTaskId)
            if (cache.taskDraftPersistence?.key === key) {
                return
            }
            const persistence = new TaskDraftPersistence(key)
            cache.taskDraftPersistence = persistence
            const state = taskDraftState(logic)
            // An optimistic handoff already owns its queue; only a fresh composer recovers as a draft.
            if (!state.draft && !state.queuedText) {
                const restored = persistence.restore()
                if (restored?.draft) {
                    cache.restoringTaskDraft = true
                    actions.setDraftRecovery(restored.recovery)
                    actions.setComposerFormValues({ draft: restored.draft })
                    cache.restoringTaskDraft = false
                }
            }
            save()
        },
        persistTaskDraft: save,
        beginTaskDraftDelivery: ({ content }: { content: string }): void => {
            const persistence: TaskDraftPersistence | undefined = cache.taskDraftPersistence
            persistence?.startDelivery(content)
        },
        finishTaskDraftDelivery: (): void => {
            const persistence: TaskDraftPersistence | undefined = cache.taskDraftPersistence
            persistence?.finishDelivery(taskDraftState(logic))
        },
        setComposerFormValue: save,
        setComposerFormValues: save,
        resetComposerForm: save,
        enqueueMessage: save,
        prependQueuedMessage: save,
        updateQueuedMessage: save,
        removeQueuedMessage: save,
        clearQueue: save,
    }
}
