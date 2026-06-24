import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner, LemonButton, LemonSkeleton, LemonTextArea } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'

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
    const streamLogic = sandboxStreamLogic({ streamKey: runId })
    const { pendingPermissionRequest, currentRunStatus, threadItems, logBootstrapLoading, bootstrapError } =
        useValues(streamLogic)
    const { reset, bootstrapRun } = useActions(streamLogic)
    const { sendMessage } = useActions(taskRunChatLogic({ taskId, runId }))
    const { sendingMessage } = useValues(taskRunChatLogic({ taskId, runId }))

    const isTerminal = isTerminalRunStatus(currentRunStatus)
    const [composerText, setComposerText] = useState('')

    const isQuestion = !!pendingPermissionRequest?.questions && pendingPermissionRequest.questions.length > 0
    const isLogPending = logBootstrapLoading
    const showBootstrapError =
        !!bootstrapError && threadItems.length === 1 && threadItems[0]?.type === 'error' && !isLogPending
    const isBlockingBootstrapState = isLogPending || showBootstrapError

    const handleSend = (): void => {
        const trimmed = composerText.trim()
        if (!trimmed || sendingMessage || isTerminal || isBlockingBootstrapState) {
            return
        }
        sendMessage(trimmed)
        setComposerText('')
    }

    const handleRetryBootstrap = (): void => {
        reset()
        bootstrapRun({ taskId, runId })
    }

    return (
        <div className="flex flex-col h-full overflow-hidden">
            <div className="flex-1 min-h-0">
                {isLogPending ? (
                    <TaskRunLogSkeleton />
                ) : showBootstrapError && bootstrapError?.status === 404 ? (
                    <NotFound object="task run" className="m-0 py-8" />
                ) : showBootstrapError && bootstrapError ? (
                    <LemonBanner
                        type="error"
                        data-attr="task-run-log-error"
                        action={{
                            children: 'Retry',
                            onClick: handleRetryBootstrap,
                        }}
                    >
                        <p>We couldn't load this task run.</p>
                        <p className="text-muted mb-0">{bootstrapError.errorMessage || bootstrapError.errorTitle}</p>
                    </LemonBanner>
                ) : (
                    <SandboxThreadView />
                )}
            </div>

            {!isBlockingBootstrapState && <SandboxResourcesBar />}

            {pendingPermissionRequest && !isTerminal && !isBlockingBootstrapState && (
                <div className="border-t px-4 py-3">
                    {isQuestion ? (
                        <SandboxQuestionInput streamKey={runId} request={pendingPermissionRequest} />
                    ) : (
                        <SandboxPermissionInput streamKey={runId} request={pendingPermissionRequest} />
                    )}
                </div>
            )}

            {!isTerminal && !pendingPermissionRequest && !isBlockingBootstrapState && (
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

            {!isBlockingBootstrapState && <SandboxContextUsage />}
        </div>
    )
}

function TaskRunLogSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-3 p-4" data-attr="task-run-log-skeleton">
            <LemonSkeleton className="h-4 w-1/3" />
            <LemonSkeleton className="h-16 w-11/12" />
            <LemonSkeleton className="h-4 w-1/4 ml-auto" />
            <LemonSkeleton className="h-24 w-4/5 ml-auto opacity-60" />
            <LemonSkeleton className="h-20 w-10/12 opacity-40" />
        </div>
    )
}
