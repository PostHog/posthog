import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import {
    isTerminalRunStatus,
    SandboxContextUsage,
    SandboxPermissionInput,
    SandboxQuestionInput,
    SandboxResourcesBar,
    SandboxThreadView,
    sandboxStreamLogic,
} from 'products/posthog_ai/frontend/sandbox'

import { taskRunChatLogic } from '../logics/taskRunChatLogic'

export interface TaskRunChatProps {
    taskId: string
    runId: string
}

export function TaskRunChat({ taskId, runId }: TaskRunChatProps): JSX.Element {
    // The outer BindLogic binds the shared sandboxStreamLogic instance (keyed by runId) consumed by
    // both the renderer (thread/permission/question views) and taskRunChatLogic. We bind in live mode;
    // bootstrapRun (called from taskRunChatLogic.afterMount) reads the run status from the tasks API and
    // never opens SSE for an already-terminal run — same pattern SandboxRunViewer uses.
    return (
        <BindLogic logic={sandboxStreamLogic} props={{ streamKey: runId }}>
            <BindLogic logic={taskRunChatLogic} props={{ taskId, runId }}>
                <TaskRunChatContent taskId={taskId} runId={runId} />
            </BindLogic>
        </BindLogic>
    )
}

function TaskRunChatContent({ taskId, runId }: TaskRunChatProps): JSX.Element {
    const { pendingPermissionRequest, currentRunStatus } = useValues(sandboxStreamLogic({ streamKey: runId }))
    const { sendMessage } = useActions(taskRunChatLogic({ taskId, runId }))
    const { sendingMessage } = useValues(taskRunChatLogic({ taskId, runId }))

    const isTerminal = isTerminalRunStatus(currentRunStatus)
    const [composerText, setComposerText] = useState('')

    const isQuestion = !!pendingPermissionRequest?.questions && pendingPermissionRequest.questions.length > 0

    const handleSend = (): void => {
        const trimmed = composerText.trim()
        if (!trimmed || sendingMessage || isTerminal) {
            return
        }
        sendMessage(trimmed)
        setComposerText('')
    }

    return (
        <div className="flex flex-col h-full overflow-hidden">
            <div className="flex-1 overflow-y-auto flex flex-col gap-3">
                <SandboxThreadView />
            </div>

            <SandboxResourcesBar />

            {pendingPermissionRequest && !isTerminal && (
                <div className="border-t px-4 py-3">
                    {isQuestion ? (
                        <SandboxQuestionInput streamKey={runId} request={pendingPermissionRequest} />
                    ) : (
                        <SandboxPermissionInput streamKey={runId} request={pendingPermissionRequest} />
                    )}
                </div>
            )}

            {!isTerminal && !pendingPermissionRequest && (
                <div className="border-t px-4 py-3 flex gap-2 items-end">
                    <LemonTextArea
                        className="flex-1"
                        value={composerText}
                        onChange={setComposerText}
                        placeholder="Send a follow-up message…"
                        minRows={1}
                        maxRows={8}
                        onPressCmdEnter={handleSend}
                    />
                    <LemonButton
                        type="primary"
                        onClick={handleSend}
                        loading={sendingMessage}
                        disabledReason={!composerText.trim() ? 'Type a message first' : undefined}
                    >
                        Send
                    </LemonButton>
                </div>
            )}

            <SandboxContextUsage />
        </div>
    )
}
