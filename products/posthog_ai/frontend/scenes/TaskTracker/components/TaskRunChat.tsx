import { BindLogic, useActions, useValues } from 'kea'

import { runInteractionLogic, type RunInteractionLogicProps } from 'products/posthog_ai/frontend/api/logics'
import { Composer, QueuedMessageList } from 'products/posthog_ai/frontend/api/primitives'
// Eager, NOT the lazy `api/readableRun` facade: the runner scene is already a route-split chunk and the run
// surface is its primary content, so a second `lazy()` would only add a redundant chunk fetch + Suspense
// flash. The inbox embeds keep the lazy `ReadonlyRunSurface`.
import { RunSurface } from 'products/posthog_ai/frontend/api/runSurface'

import { taskDetailSceneLogic } from '../taskDetailSceneLogic'
import { ComposerModelEffortPickers } from './ComposerModelEffortPickers'

export interface TaskRunChatProps {
    taskId: string
    runId: string
    /**
     * Override for the bound run-stream key. Defaults to `runId`; set to an optimistic-create client
     * `streamKey` so this surface adopts that already-seeded/streaming instance instead of bootstrapping a
     * fresh one. Passed to both `RunSurface.Root` and `runInteractionLogic` so they never diverge.
     */
    streamKey?: string
}

/**
 * Live task-run surface. Binds `runInteractionLogic` (the Max-agnostic interaction facade, which connects to
 * the shared `runStreamLogic` keyed by `runId`) and composes the `RunSurface` compound in live mode with the
 * composer + "Up next" queue wired to it as the `RunSurface.Composer` children. The composer stays visible
 * after a run finishes; sending then starts a fresh run (seeded with the message), and `onRunStarted`
 * re-points scene selection to it. `RunSurface.Root` owns bootstrap: it reads the run status from the tasks
 * API and never opens SSE for an already-terminal run.
 */
export function TaskRunChat({ taskId, runId, streamKey }: TaskRunChatProps): JSX.Element {
    const { setSelectedRunId, loadTaskRuns } = useActions(taskDetailSceneLogic({ taskId }))
    const { selectedRun } = useValues(taskDetailSceneLogic({ taskId }))
    const logicProps: RunInteractionLogicProps = {
        taskId,
        runId,
        streamKey,
        currentModel: selectedRun?.state?.model,
        currentEffort: selectedRun?.state?.reasoning_effort,
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
    const { composerForm, isSubmitting, isBusy, queuedMessages, isTerminal, selectedModel, selectedEffort } = useValues(
        runInteractionLogic(logicProps)
    )
    const {
        setComposerFormValues,
        submitComposerForm,
        cancelRun,
        updateQueuedMessage,
        removeQueuedMessage,
        setModel,
        setEffort,
    } = useActions(runInteractionLogic(logicProps))

    return (
        // `RunSurface.Root` and `runInteractionLogic` deliberately share the same stream key (`streamKey ?? runId`,
        // resolved inside each): the composer slot's gating must read the exact stream the thread renders. The
        // optional `streamKey` lets both adopt an optimistic-create instance — keep them aligned, never diverging.
        <RunSurface.Root
            taskId={logicProps.taskId}
            runId={logicProps.runId}
            streamKey={logicProps.streamKey}
            interaction="live"
        >
            <div className="@container/thread flex flex-col h-full -mx-4">
                <RunSurface.Thread className="flex-1 min-h-0" listClassName="py-4" rowClassName="px-4" />
                <RunSurface.Composer>
                    <RunSurface.Resources />
                    <Composer.Root
                        value={composerForm.draft}
                        onChange={(value) => setComposerFormValues({ draft: value })}
                        onSubmit={submitComposerForm}
                        loading={isSubmitting}
                        isTurnActive={isBusy}
                        onStop={() => cancelRun()}
                    >
                        {queuedMessages.length > 0 && (
                            <Composer.Banner>
                                <QueuedMessageList
                                    messages={queuedMessages}
                                    onUpdate={updateQueuedMessage}
                                    onRemove={removeQueuedMessage}
                                />
                            </Composer.Banner>
                        )}
                        <Composer.Frame>
                            <Composer.Field>
                                <Composer.Placeholder>
                                    {isTerminal ? 'Send a message to start a new run…' : 'Send a follow-up message…'}
                                </Composer.Placeholder>
                                <Composer.Textarea data-attr="sandbox-composer-input" submitShortcut="cmd-enter" />
                            </Composer.Field>
                            <Composer.Footer>
                                {/* Model/effort picker: selection lives in the bound runInteractionLogic and is
                                applied when the message is sent — synced to the running agent on a follow-up,
                                or used to seed the next run once terminal. */}
                                <ComposerModelEffortPickers
                                    selectedModel={selectedModel}
                                    selectedEffort={selectedEffort}
                                    onModelChange={setModel}
                                    onEffortChange={setEffort}
                                />
                            </Composer.Footer>
                        </Composer.Frame>
                        <Composer.Submit data-attr="sandbox-composer-send" />
                    </Composer.Root>
                </RunSurface.Composer>
            </div>
        </RunSurface.Root>
    )
}
