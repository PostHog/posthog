import { BindLogic, useActions, useValues } from 'kea'

import { SandboxRunViewer } from 'products/posthog_ai/frontend/sandbox'

import { taskRunChatLogic } from '../logics/taskRunChatLogic'

export interface TaskRunChatProps {
    taskId: string
    runId: string
}

/**
 * Live task-run surface. Binds `taskRunChatLogic` (which connects to the shared `sandboxStreamLogic`
 * keyed by `runId`) and renders `SandboxRunViewer` in live mode with the composer wired to the task-run
 * command logic. The viewer owns bootstrap: it reads the run status from the tasks API and never opens
 * SSE for an already-terminal run.
 */
export function TaskRunChat({ taskId, runId }: TaskRunChatProps): JSX.Element {
    return (
        <BindLogic logic={taskRunChatLogic} props={{ taskId, runId }}>
            <TaskRunChatContent taskId={taskId} runId={runId} />
        </BindLogic>
    )
}

function TaskRunChatContent({ taskId, runId }: TaskRunChatProps): JSX.Element {
    const { composerDraft, sendingMessage } = useValues(taskRunChatLogic({ taskId, runId }))
    const { setComposerDraft, sendMessage } = useActions(taskRunChatLogic({ taskId, runId }))

    return (
        <SandboxRunViewer
            taskId={taskId}
            runId={runId}
            interaction="live"
            composerValue={composerDraft}
            onComposerChange={setComposerDraft}
            onComposerSubmit={() => sendMessage(composerDraft)}
            composerLoading={sendingMessage}
        />
    )
}
