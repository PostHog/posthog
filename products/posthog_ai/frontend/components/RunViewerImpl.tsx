import { BindLogic, useActions, useValues } from 'kea'
import { createContext, type ReactNode, useContext, useEffect } from 'react'

import { cn } from 'lib/utils/css-classes'

import type { QueuedMessage } from '../logics/runInteractionLogic'
import { isTerminalRunStatus, runStreamLogic } from '../logics/runStreamLogic'
import { Composer } from './composer/Composer'
import { ContextUsageBar } from './ContextUsageBar'
import { PermissionInput } from './PermissionInput'
import { QuestionInput } from './QuestionInput'
import { QueuedMessageList } from './QueuedMessageList'
import { ResourcesBar } from './ResourcesBar'
import { RunLogSkeleton } from './RunLogSkeleton'
import { ThreadView } from './ThreadView'

export interface RunViewerProps {
    taskId: string
    runId: string
    /** Stable logic key; defaults to `runId` (the run is the unit being viewed). */
    streamKey?: string
    /** Telemetry tag only — omit for conversation-less runs (automation, Slack, signals, PR-triggered). */
    conversationId?: string
    /**
     * `'read-only'` (default) replays the persisted `logs/` snapshot once and never opens SSE — the safe
     * choice for a static viewer. `'live'` streams an in-progress run over SSE (falling back to replay once
     * terminal) and adds approvals/questions plus the follow-up composer. The mode is folded into the logic
     * key, so a live and a read-only viewer of the same run can never share state.
     */
    interaction?: 'live' | 'read-only'
    className?: string
    /** Applied to the thread's list wrapper (`VirtualizedThread.Root`), not the react-window scroll viewport. */
    threadListClassName?: string
    /** Applied to each thread item row's centered content (`VirtualizedThread.Row`); header/footer rows excluded. */
    threadRowClassName?: string
    /**
     * Composer wiring — live mode only. Provide all of `composerValue`/`onComposerChange`/`onComposerSubmit`
     * to render the follow-up composer; the consumer owns the draft and the send (this module never POSTs
     * task commands itself). Omit to stream live without a composer.
     */
    composerValue?: string
    onComposerChange?: (value: string) => void
    onComposerSubmit?: () => void
    composerLoading?: boolean
    composerPlaceholder?: string
    /**
     * Editable "Up next" queue — live mode only, rendered above the composer when non-empty. Provide all
     * three to surface staged follow-ups; the consumer owns the queue (this module never mutates it).
     */
    queuedMessages?: QueuedMessage[]
    onUpdateQueuedMessage?: (id: string, content: string) => void
    onRemoveQueuedMessage?: (id: string) => void
}

// --- Compound context -------------------------------------------------------------------------------
// `RunViewer.Root` binds a `runStreamLogic` instance and bootstraps the run; the slot components
// (`RunViewer.Thread/.Prompt/.Composer/.Resources/.ContextUsage`) read the bound logic via selectors and
// the run/composer wiring from this context. Consumers either drop the prepackaged `RunViewer`
// (default slot order) or compose the slots themselves for a custom layout. State stays in the logic and
// in the caller-owned composer/queue props — the slots are presentational.

interface RunViewerContextValue {
    /** Original run id passed to `bootstrapRun`. */
    rawRunId: string
    /** Logic key (used for child stream keys). */
    runId: string
    interaction: 'live' | 'read-only'
    composer: {
        value?: string
        onChange?: (value: string) => void
        onSubmit?: () => void
        loading?: boolean
        placeholder?: string
        queuedMessages?: QueuedMessage[]
        onUpdateQueuedMessage?: (id: string, content: string) => void
        onRemoveQueuedMessage?: (id: string) => void
    }
}

const RunViewerContext = createContext<RunViewerContextValue | null>(null)

function useRunViewerContext(): RunViewerContextValue {
    const ctx = useContext(RunViewerContext)
    if (!ctx) {
        throw new Error('RunViewer.* slots must be rendered inside <RunViewer.Root> (or <RunViewer>)')
    }
    return ctx
}

export interface RunViewerRootProps extends RunViewerProps {
    /** Custom composition of `RunViewer.*` slots. Omit to render the prepackaged default layout. */
    children?: ReactNode
}

/**
 * Binds a `runStreamLogic` instance (keyed apart from any other stream of the same run), bootstraps
 * the run, and provides the run/composer context the slots read. In `'read-only'` mode it replays the
 * persisted `logs/` snapshot once — no SSE; in `'live'` mode it streams an in-progress run. Renders the
 * given slot children, or the prepackaged default layout when none are supplied.
 */
function RunViewerRoot({
    taskId,
    runId,
    streamKey,
    conversationId,
    interaction = 'read-only',
    className,
    threadListClassName,
    threadRowClassName,
    composerValue,
    onComposerChange,
    onComposerSubmit,
    composerLoading,
    composerPlaceholder,
    queuedMessages,
    onUpdateQueuedMessage,
    onRemoveQueuedMessage,
    children,
}: RunViewerRootProps): JSX.Element {
    const replayOnly = interaction !== 'live'
    const logicKey = streamKey ?? runId
    return (
        <BindLogic logic={runStreamLogic} props={{ streamKey: logicKey, conversationId, replayOnly }}>
            <RunViewerContext.Provider
                value={{
                    rawRunId: runId,
                    runId: logicKey,
                    interaction,
                    composer: {
                        value: composerValue,
                        onChange: onComposerChange,
                        onSubmit: onComposerSubmit,
                        loading: composerLoading,
                        placeholder: composerPlaceholder,
                        queuedMessages,
                        onUpdateQueuedMessage,
                        onRemoveQueuedMessage,
                    },
                }}
            >
                <RunViewerBootstrap taskId={taskId} />
                {children ?? (
                    <DefaultRunViewerLayout
                        className={className}
                        threadListClassName={threadListClassName}
                        threadRowClassName={threadRowClassName}
                    />
                )}
            </RunViewerContext.Provider>
        </BindLogic>
    )
}

/** Drives the run bootstrap as a side effect; renders nothing. Kept separate so slots stay presentational. */
function RunViewerBootstrap({ taskId }: { taskId: string }): null {
    const { rawRunId, interaction } = useRunViewerContext()
    const { bootstrapRun, reset } = useActions(runStreamLogic)

    useEffect(() => {
        // Reset first so a reused instance (stable streamKey, changed run) replays/streams the new run
        // cleanly; the bound logic keys read-only instances apart from any live stream of the same run.
        // `interaction` is in the deps so a status transition (live → terminal) re-bootstraps the right
        // mode — the bound logic re-keys on it, so `bootstrapRun`/`reset` are fresh references anyway.
        reset()
        bootstrapRun({ taskId, runId: rawRunId })
    }, [taskId, rawRunId, interaction, bootstrapRun, reset])

    return null
}

/** Thread slot: the streamed run thread, with the shared run-log skeleton during the first bootstrap. */
function RunViewerThread({
    className,
    listClassName,
    rowClassName,
}: { className?: string; listClassName?: string; rowClassName?: string } = {}): JSX.Element {
    const { bootstrapLoading, threadItems } = useValues(runStreamLogic)
    const showSkeleton = bootstrapLoading && threadItems.length === 0
    if (showSkeleton) {
        return <RunLogSkeleton className={className} listClassName={listClassName} rowClassName={rowClassName} />
    }
    // An error surfaces as a `handleStreamError` item folded into the thread, so it renders here too.
    return <ThreadView className={className} listClassName={listClassName} rowClassName={rowClassName} />
}

/**
 * Prompt slot: the pending approval / question input. Follows the non-terminal precedence — a pending
 * request replaces the composer — and renders nothing outside live mode or once the run is terminal.
 */
function RunViewerPrompt(): JSX.Element | null {
    const { interaction, runId } = useRunViewerContext()
    const { pendingPermissionRequest, currentRunStatus } = useValues(runStreamLogic)
    const showApproval = interaction === 'live' && !!pendingPermissionRequest && !isTerminalRunStatus(currentRunStatus)
    if (!showApproval) {
        return null
    }
    const isQuestion = !!pendingPermissionRequest!.questions && pendingPermissionRequest!.questions.length > 0
    return (
        <div className="border-t px-4 py-3">
            {isQuestion ? (
                <QuestionInput streamKey={runId} request={pendingPermissionRequest!} />
            ) : (
                <PermissionInput streamKey={runId} request={pendingPermissionRequest!} />
            )}
        </div>
    )
}

/**
 * Composer slot: the follow-up composer + editable "Up next" queue. Shows for any settled run status
 * (active runs take a follow-up, terminal runs start a fresh run from the typed message); hidden during
 * the `null` bootstrap window and whenever a permission/question prompt is pending. Renders nothing unless
 * the caller supplied the composer wiring (value/onChange/onSubmit).
 */
function RunViewerComposer(): JSX.Element | null {
    const { interaction, composer } = useRunViewerContext()
    const { pendingPermissionRequest, currentRunStatus } = useValues(runStreamLogic)
    const hasComposer =
        interaction === 'live' && !!composer.onSubmit && composer.onChange !== undefined && composer.value !== undefined
    if (!hasComposer || pendingPermissionRequest || currentRunStatus === null) {
        return null
    }
    const isRunTerminal = isTerminalRunStatus(currentRunStatus)
    const { queuedMessages, onUpdateQueuedMessage, onRemoveQueuedMessage } = composer
    return (
        // Composed from the logic-free Composer.* primitives directly (rather than via RunComposer) so
        // the run surface can slot its own footer/actions later. The wrapper keeps a stable `data-attr`.
        <div data-attr="composer" className="border-t px-4 py-3">
            <Composer.Root
                value={composer.value!}
                onChange={composer.onChange!}
                onSubmit={composer.onSubmit!}
                loading={composer.loading}
            >
                {queuedMessages && queuedMessages.length > 0 && onUpdateQueuedMessage && onRemoveQueuedMessage && (
                    <Composer.Banner>
                        <QueuedMessageList
                            messages={queuedMessages}
                            onUpdate={onUpdateQueuedMessage}
                            onRemove={onRemoveQueuedMessage}
                        />
                    </Composer.Banner>
                )}
                <Composer.Frame>
                    <Composer.Field>
                        <Composer.Placeholder>
                            {composer.placeholder ??
                                (isRunTerminal ? 'Send a message to start a new run…' : 'Send a follow-up message…')}
                        </Composer.Placeholder>
                        <Composer.Textarea data-attr="sandbox-composer-input" submitShortcut="cmd-enter" />
                    </Composer.Field>
                </Composer.Frame>
                <Composer.Submit data-attr="sandbox-composer-send" />
            </Composer.Root>
        </div>
    )
}

/** Default prepackaged layout: thread, then (live only) resources, prompt, composer, and context usage. */
function DefaultRunViewerLayout({
    className,
    threadClassName,
    threadListClassName,
    threadRowClassName,
}: {
    className?: string
    threadClassName?: string
    threadListClassName?: string
    threadRowClassName?: string
}): JSX.Element {
    const { interaction } = useRunViewerContext()
    if (interaction !== 'live') {
        return (
            <div className={cn('flex flex-col h-full min-h-0 w-full', className)}>
                <RunViewerThread
                    className={threadClassName}
                    listClassName={threadListClassName}
                    rowClassName={threadRowClassName}
                />
            </div>
        )
    }
    return (
        <div className={cn('@container/thread flex flex-col h-full overflow-hidden', className)}>
            <div className="flex-1 min-h-0">
                <RunViewerThread
                    className={threadClassName}
                    listClassName={threadListClassName}
                    rowClassName={threadRowClassName}
                />
            </div>
            <ResourcesBar />
            <RunViewerPrompt />
            <RunViewerComposer />
            <ContextUsageBar />
        </div>
    )
}

/**
 * Compound run surface. `RunViewer.Root` binds the stream logic and provides context; the slots
 * (`RunViewer.Thread/.Prompt/.Composer/.Resources/.ContextUsage`) compose into a custom layout, or omit
 * children for the prepackaged default. Prefer the `RunViewer` prepackaged component for the
 * common embed; reach for the slots only when a surface needs to reorder or wrap the regions.
 */
export const RunViewer = Object.assign(RunViewerRoot, {
    Root: RunViewerRoot,
    Thread: RunViewerThread,
    Prompt: RunViewerPrompt,
    Composer: RunViewerComposer,
    Resources: ResourcesBar,
    ContextUsage: ContextUsageBar,
})
