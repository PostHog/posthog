import { BindLogic, useActions, useValues } from 'kea'
import { type MutableRefObject, useEffect, useRef } from 'react'

import { userLogic } from 'scenes/userLogic'

import { runInteractionLogic, type RunInteractionLogicProps } from 'products/posthog_ai/frontend/api/logics'
// Eager, NOT the lazy `api/readableRun` facade: the runner scene is already a route-split chunk and the run
// surface is its primary content, so a second `lazy()` would only add a redundant chunk fetch + Suspense
// flash. The inbox embeds keep the lazy `ReadonlyRunSurface`.
import { RunSurface } from 'products/posthog_ai/frontend/api/runSurface'

import { RunEscapeBoundary, type RunEscapeBoundaryProps } from '../../../components/RunEscapeBoundary'
import { useForegroundStream } from '../../../hooks/useForegroundStream'
import { runCancellationLogic } from '../../../logics/runCancellationLogic'
import type { RunContinuationHandoff } from '../../../logics/runInteractionLogic'
import { taskDetailSceneLogic } from '../taskDetailSceneLogic'
import { TaskRunComposer } from './TaskRunComposer'

export interface TaskRunChatProps {
    taskId: string
    runId: string
    /**
     * Override for the bound run-stream key. Defaults to `runId`; set to an optimistic-create client
     * `streamKey` so this surface adopts that already-seeded/streaming instance instead of bootstrapping a
     * fresh one. Passed to both `RunSurface.Root` and `runInteractionLogic` so they never diverge.
     */
    streamKey?: string
    interactionKey?: string
    /** Called after a fresh run starts, in addition to the `taskDetailSceneLogic` re-pointing below. */
    onRunStarted?: (runId: string, handoff?: RunContinuationHandoff) => void
    escapeScope?: RunEscapeBoundaryProps['scope']
    initialDraft?: string
    onDraftAdopted?: () => void
    autoFocus?: boolean
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
    interactionKey,
    onRunStarted,
    escapeScope = 'chat',
    initialDraft,
    onDraftAdopted,
    autoFocus,
}: TaskRunChatProps): JSX.Element {
    const { setSelectedRunId, loadTaskRuns, continueWithRun } = useActions(taskDetailSceneLogic({ taskId }))
    const { selectedRun, task } = useValues(taskDetailSceneLogic({ taskId }))
    const { user } = useValues(userLogic)
    const flushDraftRef = useRef<() => void>(() => {})
    // Staff can view tasks they don't own (support/debugging); those are read-only — hide the composer so
    // they can't try to drive a run they can't control (the backend rejects the write anyway).
    const readOnly = !!user?.is_staff && !!task?.created_by && task.created_by.id !== user.id
    // The scene logic is keyed by task, so `selectedRun` can name a different run than this surface renders
    // — the side panel opens `task.latest_run` while the page follows a `?runId=` link or a newer run. Read
    // the run's setup only when the two agree; a mismatch would launch the successor on another run's config.
    const runConfig = selectedRun?.id === runId ? selectedRun : undefined
    const pendingInteraction = interactionKey ? runInteractionLogic.findMounted(interactionKey) : undefined
    const logicProps: RunInteractionLogicProps = {
        taskId,
        runId,
        streamKey,
        interactionKey,
        initialDraft,
        onDraftAdopted,
        flushDraft: () => flushDraftRef.current(),
        currentModel:
            runConfig?.model ??
            (typeof runConfig?.state?.model === 'string'
                ? runConfig.state.model
                : pendingInteraction?.props.currentModel),
        currentEffort:
            runConfig?.reasoning_effort ??
            (typeof runConfig?.state?.reasoning_effort === 'string'
                ? runConfig.state.reasoning_effort
                : pendingInteraction?.props.currentEffort),
        currentMode:
            typeof runConfig?.state?.initial_permission_mode === 'string'
                ? runConfig.state.initial_permission_mode
                : pendingInteraction?.props.currentMode,
        currentRuntimeAdapter: runConfig?.runtime_adapter ?? pendingInteraction?.props.currentRuntimeAdapter,
        onRunStarted: (newRunId, handoff) => {
            if (handoff) {
                continueWithRun(handoff)
            } else {
                setSelectedRunId(newRunId, taskId)
                loadTaskRuns()
            }
            // The embedded panel renders from its own creation state, so it must be re-pointed
            // when a fresh run starts.
            onRunStarted?.(newRunId, handoff)
        },
    }

    return (
        <BindLogic logic={runInteractionLogic} props={logicProps}>
            <TaskRunChatContent
                logicProps={logicProps}
                readOnly={readOnly}
                escapeScope={escapeScope}
                autoFocus={autoFocus}
                flushDraftRef={flushDraftRef}
            />
        </BindLogic>
    )
}

function TaskRunChatContent({
    logicProps,
    readOnly,
    escapeScope,
    autoFocus,
    flushDraftRef,
}: {
    logicProps: RunInteractionLogicProps
    readOnly: boolean
    escapeScope: RunEscapeBoundaryProps['scope']
    autoFocus?: boolean
    flushDraftRef: MutableRefObject<() => void>
}): JSX.Element {
    const textAreaRef = useRef<HTMLTextAreaElement>(null)
    const { handleEscape } = useActions(runInteractionLogic(logicProps))
    const { cancellationState } = useValues(runInteractionLogic(logicProps))
    const { clearCancellation } = useActions(
        runCancellationLogic({ streamKey: logicProps.streamKey ?? logicProps.runId })
    )
    useEffect(() => () => clearCancellation(), [clearCancellation])
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
            <RunEscapeBoundary
                scope={escapeScope}
                focusKey={logicProps.streamKey ?? logicProps.runId}
                textAreaRef={textAreaRef}
                onEscape={handleEscape}
                disabled={readOnly}
                className="@container/thread flex flex-col h-full -mx-4"
            >
                <RunSurface.Thread className="flex-1 min-h-0" listClassName="py-4" rowClassName="px-4" />
                {/* Stay live (stream keeps flowing) but omit the composer entirely for a read-only viewer. */}
                {!readOnly && (
                    <RunSurface.Composer isStopping={!!cancellationState}>
                        {/* The composer owns the per-keystroke draft in an isolated child so typing never re-renders
                        the thread/virtualizer rendered as its sibling above — that cascade is what made the input lag. */}
                        <TaskRunComposer
                            logicProps={logicProps}
                            textAreaRef={textAreaRef}
                            autoFocus={autoFocus}
                            flushDraftRef={flushDraftRef}
                        />
                    </RunSurface.Composer>
                )}
            </RunEscapeBoundary>
        </RunSurface.Root>
    )
}
