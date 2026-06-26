import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { isTerminalRunStatus, sandboxStreamLogic } from '../sandboxStreamLogic'
import type { QueuedMessage } from '../taskRunInteractionLogic'
import { Composer } from './composer/Composer'
import { QueuedMessageList } from './QueuedMessageList'
import { SandboxContextUsage } from './SandboxContextUsage'
import { SandboxPermissionInput } from './SandboxPermissionInput'
import { SandboxQuestionInput } from './SandboxQuestionInput'
import { SandboxResourcesBar } from './SandboxResourcesBar'
import { SandboxThreadView } from './SandboxThreadView'

export interface SandboxRunViewerProps {
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

/**
 * Embeddable viewer of a task run's agent thread. Binds a `sandboxStreamLogic` instance (keyed apart from
 * any other stream of the same run) and renders the shared `SandboxThreadView`. In `'read-only'` mode it
 * replays the persisted `logs/` snapshot once — no SSE, no composer. In `'live'` mode it streams an
 * in-progress run, surfaces permission/question prompts, and (given composer props) renders a follow-up
 * composer, automatically replaying once the run goes terminal.
 */
export function SandboxRunViewer({
    taskId,
    runId,
    streamKey,
    conversationId,
    interaction = 'read-only',
    className,
    composerValue,
    onComposerChange,
    onComposerSubmit,
    composerLoading,
    composerPlaceholder,
    queuedMessages,
    onUpdateQueuedMessage,
    onRemoveQueuedMessage,
}: SandboxRunViewerProps): JSX.Element {
    const replayOnly = interaction !== 'live'
    return (
        <BindLogic logic={sandboxStreamLogic} props={{ streamKey: streamKey ?? runId, conversationId, replayOnly }}>
            <SandboxRunViewerContent
                taskId={taskId}
                runId={streamKey ?? runId}
                rawRunId={runId}
                interaction={interaction}
                className={className}
                composerValue={composerValue}
                onComposerChange={onComposerChange}
                onComposerSubmit={onComposerSubmit}
                composerLoading={composerLoading}
                composerPlaceholder={composerPlaceholder}
                queuedMessages={queuedMessages}
                onUpdateQueuedMessage={onUpdateQueuedMessage}
                onRemoveQueuedMessage={onRemoveQueuedMessage}
            />
        </BindLogic>
    )
}

interface SandboxRunViewerContentProps {
    taskId: string
    /** Logic key (used for child stream keys). */
    runId: string
    /** Original run id passed to `bootstrapRun`. */
    rawRunId: string
    interaction: 'live' | 'read-only'
    className?: string
    composerValue?: string
    onComposerChange?: (value: string) => void
    onComposerSubmit?: () => void
    composerLoading?: boolean
    composerPlaceholder?: string
    queuedMessages?: QueuedMessage[]
    onUpdateQueuedMessage?: (id: string, content: string) => void
    onRemoveQueuedMessage?: (id: string) => void
}

function SandboxRunViewerContent({
    taskId,
    runId,
    rawRunId,
    interaction,
    className,
    composerValue,
    onComposerChange,
    onComposerSubmit,
    composerLoading,
    composerPlaceholder,
    queuedMessages,
    onUpdateQueuedMessage,
    onRemoveQueuedMessage,
}: SandboxRunViewerContentProps): JSX.Element {
    const { bootstrapLoading, threadItems, pendingPermissionRequest, currentRunStatus } = useValues(sandboxStreamLogic)
    const { bootstrapRun, reset } = useActions(sandboxStreamLogic)

    useEffect(() => {
        // Reset first so a reused instance (stable streamKey, changed run) replays/streams the new run
        // cleanly; the bound logic keys read-only instances apart from any live stream of the same run.
        // `interaction` is in the deps so a status transition (live → terminal) re-bootstraps the right
        // mode — the bound logic re-keys on it, so `bootstrapRun`/`reset` are fresh references anyway.
        reset()
        bootstrapRun({ taskId, runId: rawRunId })
    }, [taskId, rawRunId, interaction, bootstrapRun, reset])

    const isLive = interaction === 'live'
    const showSpinner = bootstrapLoading && threadItems.length === 0

    // Approvals/questions follow the existing non-terminal precedence: a pending request replaces the
    // composer. The composer itself is gated on explicit live statuses only — never during the `null`
    // bootstrap window, never for terminal runs — so a finished run can't flash a follow-up input.
    const showApproval = isLive && !!pendingPermissionRequest && !isTerminalRunStatus(currentRunStatus)
    const isQuestion = !!pendingPermissionRequest?.questions && pendingPermissionRequest.questions.length > 0
    const hasComposer = isLive && !!onComposerSubmit && onComposerChange !== undefined && composerValue !== undefined
    // The composer shows for any settled run status — active runs take a follow-up, terminal runs start a
    // fresh run from the typed message. It's hidden only during the `null` bootstrap window and while a
    // permission/question prompt is pending.
    const isRunTerminal = isTerminalRunStatus(currentRunStatus)
    const showComposer = hasComposer && !pendingPermissionRequest && currentRunStatus !== null

    const thread = showSpinner ? (
        <div className="flex justify-center py-8">
            <Spinner className="text-2xl" />
        </div>
    ) : (
        // An error surfaces as a `handleStreamError` item folded into the thread, so it renders here too.
        <SandboxThreadView />
    )

    if (!isLive) {
        return <div className={cn('flex flex-col h-full min-h-0 w-full', className)}>{thread}</div>
    }

    return (
        <div className={cn('@container/thread flex flex-col h-full overflow-hidden', className)}>
            <div className="flex-1 min-h-0">{thread}</div>

            <SandboxResourcesBar />

            {showApproval && (
                <div className="border-t px-4 py-3">
                    {isQuestion ? (
                        <SandboxQuestionInput streamKey={runId} request={pendingPermissionRequest!} />
                    ) : (
                        <SandboxPermissionInput streamKey={runId} request={pendingPermissionRequest!} />
                    )}
                </div>
            )}

            {showComposer && (
                // Composed from the logic-free Composer.* primitives directly (rather than via
                // SandboxComposer) so the run surface can slot its own footer/actions later. The
                // wrapper keeps a stable `data-attr` for the gating tests above.
                <div data-attr="composer" className="border-t px-4 py-3">
                    <Composer.Root
                        value={composerValue!}
                        onChange={onComposerChange!}
                        onSubmit={onComposerSubmit!}
                        loading={composerLoading}
                    >
                        {queuedMessages &&
                            queuedMessages.length > 0 &&
                            onUpdateQueuedMessage &&
                            onRemoveQueuedMessage && (
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
                                    {composerPlaceholder ??
                                        (isRunTerminal
                                            ? 'Send a message to start a new run…'
                                            : 'Send a follow-up message…')}
                                </Composer.Placeholder>
                                <Composer.Textarea data-attr="sandbox-composer-input" submitShortcut="cmd-enter" />
                            </Composer.Field>
                        </Composer.Frame>
                        <Composer.Submit data-attr="sandbox-composer-send" />
                    </Composer.Root>
                </div>
            )}

            <SandboxContextUsage />
        </div>
    )
}
