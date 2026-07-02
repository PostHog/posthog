import { BindLogic, useActions, useValues } from 'kea'
import { createContext, type ReactNode, useContext, useEffect } from 'react'

import { LemonDivider } from '@posthog/lemon-ui'

import { isTerminalRunStatus, runStreamLogic } from '../logics/runStreamLogic'
import { taskLogic } from '../logics/taskLogic'
import { OriginProduct } from '../types/taskTypes'
import { ContextUsageBar } from './ContextUsageBar'
import { PermissionInput } from './PermissionInput'
import { QuestionInput } from './QuestionInput'
import { ResourcesBar } from './ResourcesBar'
import { RunLogSkeleton } from './RunLogSkeleton'
import { ThreadView } from './ThreadView'

export interface RunSurfaceProps {
    taskId: string
    /**
     * The run to bootstrap and stream. Pass `null`/`''` to mount in a **pending** state — the thread renders
     * whatever's seeded in the bound `runStreamLogic` (an optimistic first message + provisioning via
     * `startOptimisticRun`) and never bootstraps; supply the real id once created to attach it on the same
     * instance (seed-preserving fast path). Requires an explicit `streamKey` while pending, since there's no
     * run id to key on.
     */
    runId: string | null
    /** Stable logic key; defaults to `runId` (the run is the unit being viewed). Required when `runId` is pending. */
    streamKey?: string
    /** Telemetry tag only — omit for conversation-less runs (automation, Slack, signals, PR-triggered). */
    conversationId?: string
    /**
     * `'read-only'` (default) replays the persisted `logs/` snapshot once and never opens SSE — the safe
     * choice for a static surface. `'live'` streams an in-progress run over SSE (falling back to replay once
     * terminal) and arms the `RunSurface.Composer` input slot (approvals/questions + the follow-up composer) —
     * but those affordances appear only if the consumer renders that slot. A consumer can stream live yet stay
     * read-only by setting `interaction='live'` and omitting `<RunSurface.Composer>`. The mode is folded into
     * the logic key, so a live and a read-only surface of the same run can never share state.
     */
    interaction?: 'live' | 'read-only'
}

// `RunSurface.Root` binds a `runStreamLogic` instance and bootstraps the run; the slot components
// (`RunSurface.Thread/.Composer/.Resources/.ContextUsage`) read the bound logic via selectors and the
// run wiring from this context. Consumers compose the slots into a custom layout — there is no default
// layout; the prepackaged read-only embed lives in `ReadonlyRunSurfaceImpl`. State stays in the logic;
// the slots are presentational and the composer UI is supplied by the consumer as children.

interface RunSurfaceContextValue {
    /** Original run id passed to `bootstrapRun`; `null`/`''` while the surface is pending (no run yet). */
    rawRunId: string | null
    /** Logic key (used for child stream keys). */
    runId: string
    interaction: 'live' | 'read-only'
    /** Run created by a Signals scout — the context-usage line is suppressed for these. */
    isScout: boolean
}

const RunSurfaceContext = createContext<RunSurfaceContextValue | null>(null)

function useRunSurfaceContext(): RunSurfaceContextValue {
    const ctx = useContext(RunSurfaceContext)
    if (!ctx) {
        throw new Error('RunSurface.* slots must be rendered inside <RunSurface.Root>')
    }
    return ctx
}

export interface RunSurfaceRootProps extends RunSurfaceProps {
    /** Custom composition of `RunSurface.*` slots. */
    children: ReactNode
}

/**
 * Binds a `runStreamLogic` instance (keyed apart from any other stream of the same run), bootstraps
 * the run, and provides the run context the slots read. In `'read-only'` mode it replays the persisted
 * `logs/` snapshot once — no SSE; in `'live'` mode it streams an in-progress run. Renders the given
 * slot children — the consumer owns the layout.
 */
function RunSurfaceRoot({
    taskId,
    runId,
    streamKey,
    conversationId,
    interaction = 'read-only',
    children,
}: RunSurfaceRootProps): JSX.Element {
    const replayOnly = interaction !== 'live'
    // A pending surface (no run id) must supply `streamKey` to key on; `runId` is the key otherwise.
    const logicKey = streamKey ?? runId ?? ''

    // The scout flag lives on the task (not the run), so the surface owns loading it once and exposing it
    // to the slots — the runner already has the task loaded, a live embed fetches it here. Only the
    // context-usage line consumes this, and only in live mode, so a read-only embed never fetches.
    const { task, taskLoading } = useValues(taskLogic({ taskId }))
    const { loadTask } = useActions(taskLogic({ taskId }))
    useEffect(() => {
        // `taskId &&`: a pending surface (optimistic create) has no task yet — don't fetch an empty id.
        if (interaction === 'live' && taskId && !task && !taskLoading) {
            loadTask()
        }
    }, [interaction, taskId, task, taskLoading, loadTask])
    const isScout = task?.origin_product === OriginProduct.SIGNALS_SCOUT

    return (
        <BindLogic logic={runStreamLogic} props={{ streamKey: logicKey, conversationId, replayOnly }}>
            <RunSurfaceContext.Provider
                value={{
                    rawRunId: runId,
                    runId: logicKey,
                    interaction,
                    isScout,
                }}
            >
                <RunSurfaceBootstrap taskId={taskId} />
                {children}
            </RunSurfaceContext.Provider>
        </BindLogic>
    )
}

/** Drives the run bootstrap as a side effect; renders nothing. Kept separate so slots stay presentational. */
function RunSurfaceBootstrap({ taskId }: { taskId: string }): null {
    const { rawRunId, interaction } = useRunSurfaceContext()
    const { bootstrapRun, reset } = useActions(runStreamLogic)
    // The bootstrap decision reads logic-resident state (not a per-component ref) so it survives the
    // optimistic create-thread → detail-page component swap onto the same `streamKey` instance.
    const { bootstrappedRunId, awaitingOptimisticAttach, currentProjectId } = useValues(runStreamLogic)

    useEffect(() => {
        // Pending: no run to bootstrap yet — leave the seeded optimistic thread (first message +
        // provisioning indicator) untouched until the consumer supplies the real id.
        if (!rawRunId) {
            return
        }
        // Wait for the project to resolve before bootstrapping — firing without it races to an
        // unretryable "No current project" error; the effect re-runs once `currentProjectId` lands.
        if (currentProjectId === null) {
            return
        }
        // Already bootstrapped this run on this instance — idempotent across re-renders and across a
        // consumer swap that adopts the same seeded instance (no reset, so the seed/stream survives).
        if (bootstrappedRunId === rawRunId) {
            return
        }
        if (awaitingOptimisticAttach) {
            // Attaching a freshly-created run to a seeded optimistic instance: skip the reset so the seed
            // survives, and take the fresh-run fast path. The live SSE echo dedups the seeded message.
            bootstrapRun({ taskId, runId: rawRunId, justCreatedRun: true })
            return
        }
        // Reset first so a reused instance (stable streamKey, changed run) replays/streams the new run
        // cleanly; the bound logic keys read-only instances apart from any live stream of the same run.
        // `interaction` is in the deps so a status transition (live → terminal) re-bootstraps the right
        // mode — the bound logic re-keys on it, so `bootstrapRun`/`reset` are fresh references anyway.
        reset()
        bootstrapRun({ taskId, runId: rawRunId })
    }, [
        taskId,
        rawRunId,
        interaction,
        bootstrappedRunId,
        awaitingOptimisticAttach,
        currentProjectId,
        bootstrapRun,
        reset,
    ])

    return null
}

/** Thread slot: the streamed run thread, with the shared run-log skeleton during the first bootstrap. */
function RunSurfaceThread({
    className,
    listClassName,
    rowClassName,
}: { className?: string; listClassName?: string; rowClassName?: string } = {}): JSX.Element {
    const { interaction, isScout } = useRunSurfaceContext()
    const { bootstrapLoading, threadItems } = useValues(runStreamLogic)
    const showSkeleton = bootstrapLoading && threadItems.length === 0
    if (showSkeleton) {
        return <RunLogSkeleton className={className} listClassName={listClassName} rowClassName={rowClassName} />
    }
    // Context usage rides the thread footer for live runs (the meta bars are live-only), but never for a
    // scout run. An error surfaces as a `handleStreamError` item folded into the thread, so it renders here too.
    return (
        <ThreadView
            className={className}
            listClassName={listClassName}
            rowClassName={rowClassName}
            showContextUsage={interaction === 'live' && !isScout}
        />
    )
}

/**
 * Input-region slot: owns prompt-vs-composer precedence and the null-bootstrap gate. While a permission /
 * question request is pending (and the run isn't terminal) it renders the approval prompt; otherwise it
 * renders the consumer's composer `children`. Renders nothing outside live mode, during the `null` bootstrap
 * window, or when no composer children are supplied (e.g. `ReadonlyRunSurface`). The composer thus shows for
 * any settled run status (active runs take a follow-up, terminal runs start a fresh run from the typed
 * message), is hidden during bootstrap, and is replaced by the prompt while a request is pending.
 */
function RunSurfaceComposer({ children }: { children?: ReactNode }): JSX.Element | null {
    const { interaction, runId } = useRunSurfaceContext()
    const { pendingPermissionRequest, currentRunStatus } = useValues(runStreamLogic)
    if (interaction !== 'live') {
        return null
    }
    // Pending approval/question takes precedence over the composer.
    if (pendingPermissionRequest && !isTerminalRunStatus(currentRunStatus)) {
        const isQuestion = !!pendingPermissionRequest.questions && pendingPermissionRequest.questions.length > 0
        return (
            <div className="border-t px-4 py-3">
                <div className="mx-auto w-full max-w-180">
                    {isQuestion ? (
                        <QuestionInput streamKey={runId} request={pendingPermissionRequest} />
                    ) : (
                        <PermissionInput streamKey={runId} request={pendingPermissionRequest} />
                    )}
                </div>
            </div>
        )
    }
    if (!children || currentRunStatus === null) {
        return null // no composer UI supplied (e.g. ReadonlyRunSurface) or pre-bootstrap
    }
    return (
        <div data-attr="composer" className="px-4 pb-4">
            <LemonDivider className="mt-0 mb-3" />
            <div className="mx-auto w-full max-w-180 space-y-2">{children}</div>
        </div>
    )
}

/**
 * Compound run surface. `RunSurface.Root` binds the stream logic, bootstraps the run, and provides context;
 * the slots (`RunSurface.Thread/.Composer/.Resources/.ContextUsage`) compose into a custom layout — there is
 * no default layout. `RunSurface.Composer` owns the prompt-vs-composer precedence and takes the composer UI
 * as children; the meta slots (`.Resources`/`.ContextUsage`) self-bind and self-hide when empty. For the
 * common no-input embed, prefer the prepackaged `ReadonlyRunSurface` (api/readableRun).
 */
export const RunSurface = Object.assign(RunSurfaceRoot, {
    Root: RunSurfaceRoot,
    Thread: RunSurfaceThread,
    Composer: RunSurfaceComposer,
    Resources: ResourcesBar,
    ContextUsage: ContextUsageBar,
})
