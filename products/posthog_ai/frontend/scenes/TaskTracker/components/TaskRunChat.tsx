import { BindLogic, useActions, useValues } from 'kea'

import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { userLogic } from 'scenes/userLogic'

import { runInteractionLogic, type RunInteractionLogicProps } from 'products/posthog_ai/frontend/api/logics'
import { Composer, QueuedMessageList } from 'products/posthog_ai/frontend/api/primitives'
// Eager, NOT the lazy `api/readableRun` facade: the runner scene is already a route-split chunk and the run
// surface is its primary content, so a second `lazy()` would only add a redundant chunk fetch + Suspense
// flash. The inbox embeds keep the lazy `ReadonlyRunSurface`.
import { RunSurface } from 'products/posthog_ai/frontend/api/runSurface'
import { cycleMode } from 'products/posthog_ai/frontend/utils/composerModes'

import { AttachedContextBar } from '../../../components/composer/AttachedContextBar'
import { ComposerModelEffortPickers } from '../../../components/composer/ComposerModelEffortPickers'
import { ComposerModePicker } from '../../../components/composer/ComposerModePicker'
import { ComposerModeShortcut } from '../../../components/composer/ComposerModeShortcut'
import { useDebouncedDraft } from '../../../components/composer/useDebouncedDraft'
import { useForegroundStream } from '../../../hooks/useForegroundStream'
import { taskDetailSceneLogic } from '../taskDetailSceneLogic'

export interface TaskRunChatProps {
    taskId: string
    runId: string
    /**
     * Override for the bound run-stream key. Defaults to `runId`; set to an optimistic-create client
     * `streamKey` so this surface adopts that already-seeded/streaming instance instead of bootstrapping a
     * fresh one. Passed to both `RunSurface.Root` and `runInteractionLogic` so they never diverge.
     */
    streamKey?: string
    /** Called after a fresh run starts, in addition to the `taskDetailSceneLogic` re-pointing below. */
    onRunStarted?: (runId: string) => void
    /**
     * Scroll-content padding for the thread list. Hosts that overlay chrome on the thread's top edge (the
     * side panel's floating header) pass extra top padding here so content clears the chrome at rest while
     * still scrolling behind it.
     */
    threadListClassName?: string
}

/**
 * Live task-run surface. Binds `runInteractionLogic` (the Max-agnostic interaction facade, which connects to
 * the shared `runStreamLogic` keyed by `runId`) and composes the `RunSurface` compound in live mode with the
 * composer + "Up next" queue wired to it as the `RunSurface.Composer` children. The composer stays visible
 * after a run finishes; sending then starts a fresh run (seeded with the message), and `onRunStarted`
 * re-points scene selection to it. `RunSurface.Root` owns bootstrap: it reads the run status from the tasks
 * API and never opens SSE for an already-terminal run.
 */
export function TaskRunChat({
    taskId,
    runId,
    streamKey,
    onRunStarted,
    threadListClassName = 'py-4',
}: TaskRunChatProps): JSX.Element {
    const { setSelectedRunId, loadTaskRuns } = useActions(taskDetailSceneLogic({ taskId }))
    const { selectedRun, task } = useValues(taskDetailSceneLogic({ taskId }))
    const { user } = useValues(userLogic)
    // Staff can view tasks they don't own (support/debugging); those are read-only — hide the composer so
    // they can't try to drive a run they can't control (the backend rejects the write anyway).
    const readOnly = !!user?.is_staff && !!task?.created_by && task.created_by.id !== user.id
    const logicProps: RunInteractionLogicProps = {
        taskId,
        runId,
        streamKey,
        currentModel: selectedRun?.state?.model,
        currentEffort: selectedRun?.state?.reasoning_effort,
        currentMode: selectedRun?.state?.initial_permission_mode,
        onRunStarted: (newRunId) => {
            setSelectedRunId(newRunId, taskId)
            loadTaskRuns()
            // The embedded panel renders from its own creation state, so it must be re-pointed
            // when a fresh run starts.
            onRunStarted?.(newRunId)
        },
    }

    return (
        <BindLogic logic={runInteractionLogic} props={logicProps}>
            <TaskRunChatContent logicProps={logicProps} readOnly={readOnly} threadListClassName={threadListClassName} />
        </BindLogic>
    )
}

function TaskRunChatContent({
    logicProps,
    readOnly,
    threadListClassName,
}: {
    logicProps: RunInteractionLogicProps
    readOnly: boolean
    threadListClassName: string
}): JSX.Element {
    // This surface renders the approval card, so persist tools must prompt here — register as a
    // foreground stream (same key resolution as `RunSurface.Root`). A read-only staff view omits the
    // composer and could never answer a forced prompt, so it stays a background consumer.
    useForegroundStream(readOnly ? null : (logicProps.streamKey ?? logicProps.runId))
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
                <RunSurface.Thread
                    className="flex-1 min-h-0"
                    listClassName={threadListClassName}
                    rowClassName="px-4"
                    // The composer floats over the thread's bottom edge (glass chrome, the thread scrolls
                    // behind it) rather than sitting below it as a flex sibling — the legacy sidebar look.
                    // Stay live (stream keeps flowing) but omit the composer entirely for a read-only viewer.
                    bottomOverlay={
                        !readOnly ? (
                            <RunSurface.Composer>
                                {/* The composer owns the per-keystroke draft in an isolated child so typing never
                                re-renders the thread/virtualizer it overlays — that cascade is what made the input lag. */}
                                <LiveComposer logicProps={logicProps} />
                            </RunSurface.Composer>
                        ) : undefined
                    }
                />
            </div>
        </RunSurface.Root>
    )
}

function LiveComposer({ logicProps }: { logicProps: RunInteractionLogicProps }): JSX.Element {
    const {
        composerForm,
        isSubmitting,
        isBusy,
        queuedMessages,
        isTerminal,
        selectedModel,
        selectedEffort,
        consentBlocked,
        selectedMode,
    } = useValues(runInteractionLogic(logicProps))
    const {
        setComposerFormValues,
        submitComposerForm,
        cancelRun,
        updateQueuedMessage,
        removeQueuedMessage,
        setModel,
        setEffort,
        clearConsentBlock,
        setMode,
    } = useActions(runInteractionLogic(logicProps))

    const draft = useDebouncedDraft(composerForm.draft, (value) => setComposerFormValues({ draft: value }))

    return (
        <>
            {/* Inside the slot children: detaches while a pending approval replaces the composer. */}
            <ComposerModeShortcut onCycle={() => setMode(cycleMode(selectedMode))} />
            <Composer.Root
                value={draft.value}
                onChange={draft.onChange}
                onSubmit={() => draft.submit(submitComposerForm)}
                loading={isSubmitting}
                isTurnActive={isBusy}
                onStop={() => cancelRun()}
                // The legacy sidebar's floating chrome: bordered translucent glass around an inset frame.
                // This composer overlays the thread (see `bottomOverlay` above), which scrolls behind it,
                // blurred through the glass. `px-0`: the `RunSurface.Composer` wrapper already provides the
                // horizontal inset, keeping the card aligned with the thread rows. Pointer events come back
                // on at the glass card so the gutters around it stay click-through to the thread.
                isSticky
                isThreadVisible
                containerClassName="px-0"
                className="pointer-events-auto"
            >
                <RunSurface.Resources className="pt-2" />
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
                    <Composer.Header>
                        <AttachedContextBar />
                    </Composer.Header>
                    <Composer.Field>
                        <Composer.Placeholder>
                            {isTerminal ? 'Send a message to start a new run…' : 'Send a follow-up message…'}
                        </Composer.Placeholder>
                        <Composer.Textarea data-attr="sandbox-composer-input" />
                    </Composer.Field>
                    <Composer.Footer className="flex flex-wrap items-center gap-1 pl-2">
                        {/* Mode + model/effort pickers: selection lives in the bound runInteractionLogic and is
                        applied when the message is sent — synced to the running agent on a follow-up,
                        or used to seed the next run once terminal. */}
                        <ComposerModePicker selectedMode={selectedMode} onModeChange={setMode} />
                        <ComposerModelEffortPickers
                            selectedModel={selectedModel}
                            selectedEffort={selectedEffort}
                            onModelChange={setModel}
                            onEffortChange={setEffort}
                        />
                    </Composer.Footer>
                </Composer.Frame>
                <AIConsentPopoverWrapper
                    placement="top-end"
                    showArrow
                    ignoreDismissal
                    hidden={!consentBlocked}
                    onApprove={() => submitComposerForm()}
                    onDismiss={() => clearConsentBlock()}
                >
                    <Composer.Submit data-attr="sandbox-composer-send" />
                </AIConsentPopoverWrapper>
            </Composer.Root>
        </>
    )
}
