import { BindLogic, useActions, useValues } from 'kea'

import { runInteractionLogic, type RunInteractionLogicProps } from 'products/posthog_ai/frontend/api/logics'
import { RunViewer } from 'products/posthog_ai/frontend/api/run'

import { taskDetailSceneLogic } from '../taskDetailSceneLogic'

export interface TaskRunChatProps {
    taskId: string
    runId: string
}

/**
 * Live task-run surface. Binds `runInteractionLogic` (the Max-agnostic interaction facade, which
 * connects to the shared `runStreamLogic` keyed by `runId`) and renders `RunViewer` in live
 * mode with the composer + "Up next" queue wired to it. The composer stays visible after a run finishes;
 * sending then starts a fresh run (seeded with the message), and `onRunStarted` re-points scene selection
 * to it. The viewer owns bootstrap: it reads the run status from the tasks API and never opens SSE for an
 * already-terminal run.
 */
export function TaskRunChat({ taskId, runId }: TaskRunChatProps): JSX.Element {
    const { setSelectedRunId, loadTaskRuns } = useActions(taskDetailSceneLogic({ taskId }))
    const logicProps: RunInteractionLogicProps = {
        taskId,
        runId,
        onRunStarted: (newRunId) => {
            setSelectedRunId(newRunId, taskId)
            loadTaskRuns()
        },
    }

    return (
        <BindLogic logic={runInteractionLogic} props={logicProps}>
            <TaskRunChatContent logicProps={logicProps} />
        </BindLogic>
    )
}

function TaskRunChatContent({ logicProps }: { logicProps: RunInteractionLogicProps }): JSX.Element {
    const { draft, isSubmitting, queuedMessages } = useValues(runInteractionLogic(logicProps))
    const { setDraft, submit, updateQueuedMessage, removeQueuedMessage } = useActions(runInteractionLogic(logicProps))

    return (
        <RunViewer
            taskId={logicProps.taskId}
            runId={logicProps.runId}
            interaction="live"
            composerValue={draft}
            onComposerChange={setDraft}
            onComposerSubmit={submit}
            composerLoading={isSubmitting}
            queuedMessages={queuedMessages}
            onUpdateQueuedMessage={updateQueuedMessage}
            onRemoveQueuedMessage={removeQueuedMessage}
        />
    )
}
