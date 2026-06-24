import { BindLogic, useActions, useValues } from 'kea'

import { SandboxRunViewer, taskRunInteractionLogic } from 'products/posthog_ai/frontend/sandbox'

export interface TaskRunChatProps {
    taskId: string
    runId: string
}

/**
 * Live task-run surface. Binds `taskRunInteractionLogic` (the Max-agnostic interaction facade, which
 * connects to the shared `sandboxStreamLogic` keyed by `runId`) and renders `SandboxRunViewer` in live
 * mode with the composer + "Up next" queue wired to it. The viewer owns bootstrap: it reads the run status
 * from the tasks API and never opens SSE for an already-terminal run.
 */
export function TaskRunChat({ taskId, runId }: TaskRunChatProps): JSX.Element {
    return (
        <BindLogic logic={taskRunInteractionLogic} props={{ taskId, runId }}>
            <TaskRunChatContent taskId={taskId} runId={runId} />
        </BindLogic>
    )
}

function TaskRunChatContent({ taskId, runId }: TaskRunChatProps): JSX.Element {
    const { draft, sending, queuedMessages } = useValues(taskRunInteractionLogic({ taskId, runId }))
    const { setDraft, submit, updateQueuedMessage, removeQueuedMessage } = useActions(
        taskRunInteractionLogic({ taskId, runId })
    )

    return (
        <SandboxRunViewer
            taskId={taskId}
            runId={runId}
            interaction="live"
            composerValue={draft}
            onComposerChange={setDraft}
            onComposerSubmit={submit}
            composerLoading={sending}
            queuedMessages={queuedMessages}
            onUpdateQueuedMessage={updateQueuedMessage}
            onRemoveQueuedMessage={removeQueuedMessage}
        />
    )
}
