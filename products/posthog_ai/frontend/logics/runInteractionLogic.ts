import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { projectLogic } from 'scenes/projectLogic'

import {
    DEFAULT_COMPOSER_EFFORT,
    DEFAULT_COMPOSER_MODEL,
    resolveEffortForModel,
} from 'products/posthog_ai/frontend/utils/composerModels'
import { tasksRunCreate, tasksRunsCommandCreate } from 'products/tasks/frontend/generated/api'
import {
    ClaudeRuntimeAdapterEnumApi,
    type ClaudeTaskRunCreateSchemaApi,
    type ReasoningEffortEnumApi,
} from 'products/tasks/frontend/generated/api.schemas'

import { type AttachedContextItem, attachedContextItemKey } from '../types/contextTypes'
import { wrapWithPosthogContext } from '../utils/posthogContextBlock'
import { attachedContextLogic } from './attachedContextLogic'
import type { runInteractionLogicType } from './runInteractionLogicType'
import { isTerminalRunStatus, runStreamLogic } from './runStreamLogic'

export interface RunInteractionLogicProps {
    taskId: string
    runId: string
    /**
     * Optional override for the bound `runStreamLogic` key. The logic still keys its own per-run state by
     * `runId` (queue, model/effort overrides), but connects to the stream under `streamKey ?? runId` so it
     * can adopt an optimistic-create instance seeded under a client `streamKey` — sharing the exact stream
     * `RunSurface` binds, never diverging from it. API calls still use the real `runId`.
     */
    streamKey?: string
    /** The run's stored model / reasoning effort, injected by the consumer. They seed the picker's display and
     * the config a terminal-run send launches the next run with (override ?? this ?? default). */
    currentModel?: string | null
    currentEffort?: string | null
    /** Called with the new run's id after a terminal-run send starts a fresh run, so the surface can
     * re-point selection to it (the run lifecycle / selection is a tasks-scene concern, injected here). */
    onRunStarted?: (runId: string) => void
}

/** The follow-up staged in the "Up next" buffer while the agent is mid-turn. */
export interface QueuedMessage {
    id: string
    content: string
}

/** Stable id for the single staged "Up next" message — the queue never holds more than one. */
const QUEUED_MESSAGE_ID = 'queued'

// Agent-server (ACP) session config option ids — see the `/code` agent's buildConfigOptions. The model
// option's id is `model`; the effort option's id is `effort` (its category is `thought_level`).
const MODEL_CONFIG_ID = 'model'
const EFFORT_CONFIG_ID = 'effort'

/**
 * Max-agnostic interaction facade for a single task run. The UI binds to this one logic to drive every
 * user → run interaction — sending follow-ups, staging an editable "Up next" message while the agent is
 * busy, and (re-exposed from `runStreamLogic`) answering questions / approving operations. It owns no
 * transport: the SSE stream, thread projection, run status, and permission routing all live in
 * `runStreamLogic`, which this connects to by `streamKey` (the `runId`).
 *
 * Queueing is client-side and holds at most a single message: a follow-up typed while the agent is working
 * a turn is staged here (editable, removable), and a second follow-up typed before the turn ends is
 * concatenated onto it rather than fanning out into separate messages. The single staged message is flushed
 * as one `user_message` when the turn completes. This mirrors the PostHog AI sandbox flush path without any
 * conversation/Max coupling.
 */
export const runInteractionLogic = kea<runInteractionLogicType>([
    path(['products', 'posthog_ai', 'frontend', 'logics', 'runInteractionLogic']),
    props({} as RunInteractionLogicProps),
    key((props) => props.runId),

    connect((props: RunInteractionLogicProps) => ({
        values: [
            projectLogic,
            ['currentProjectId'],
            runStreamLogic({ streamKey: props.streamKey ?? props.runId }),
            ['currentRunStatus', 'pendingPermissionRequest', 'respondingToPermission', 'isThinking'],
            attachedContextLogic,
            ['contextItems', 'sentContextKeysByTask'],
        ],
        actions: [
            runStreamLogic({ streamKey: props.streamKey ?? props.runId }),
            ['pushHumanMessage', 'respondToPermission', 'cancelRun', 'markTurnComplete'],
            attachedContextLogic,
            ['markContextSent'],
        ],
    })),

    actions({
        setSending: (sending: boolean) => ({ sending }),
        // Start a fresh run on the task, seeded with this message and chained from the finished run.
        startNewRun: (content: string) => ({ content }),
        setStartingRun: (starting: boolean) => ({ starting }),
        // Internal: POST one `user_message` now. `source` says where the content lives so a successful send
        // clears the right place and a failed send preserves it for retry ('draft' → composer, 'queue' →
        // the staged buffer combined into this send).
        sendNow: (content: string, source: 'draft' | 'queue') => ({ content, source }),
        // Stage a follow-up, concatenating onto any message already queued so the buffer stays a single message.
        enqueueMessage: (content: string) => ({ content }),
        // Re-stage unsent content ahead of anything queued since — used to restore a failed queue flush.
        prependQueuedMessage: (content: string) => ({ content }),
        updateQueuedMessage: (id: string, content: string) => ({ id, content }),
        removeQueuedMessage: (id: string) => ({ id }),
        clearQueue: true,
        // Internal: drain the staged "Up next" message when the agent is idle.
        flushQueue: true,
        // Pick the model / reasoning effort for the next message. Selection is held client-side only and
        // synced to the running agent (via `set_config_option`) at send time — not on each pick. The backend
        // doesn't persist live changes back to the run state, so the override is the source of truth.
        setModel: (model: string) => ({ model }),
        setEffort: (effort: string) => ({ effort }),
        // Internal: record the model / effort last synced to the agent session, so a send only fires a
        // `set_config_option` when the pick actually differs from what the session is already running.
        setSentModel: (model: string) => ({ model }),
        setSentEffort: (effort: string) => ({ effort }),
    }),

    reducers({
        sending: [
            false,
            {
                setSending: (_, { sending }) => sending,
            },
        ],
        startingRun: [
            false,
            {
                setStartingRun: (_, { starting }) => starting,
            },
        ],
        queuedMessages: [
            [] as QueuedMessage[],
            {
                // The buffer holds a single message under a stable id — a second follow-up concatenates onto
                // the staged content rather than appending a new entry.
                enqueueMessage: (state, { content }) =>
                    state.length > 0
                        ? [{ id: QUEUED_MESSAGE_ID, content: `${state[0].content}\n\n${content}` }]
                        : [{ id: QUEUED_MESSAGE_ID, content }],
                // Restore the unsent content in front of anything staged since, preserving send order.
                prependQueuedMessage: (state, { content }) =>
                    state.length > 0
                        ? [{ id: QUEUED_MESSAGE_ID, content: `${content}\n\n${state[0].content}` }]
                        : [{ id: QUEUED_MESSAGE_ID, content }],
                updateQueuedMessage: (state, { id, content }) =>
                    state.map((message) => (message.id === id ? { ...message, content } : message)),
                removeQueuedMessage: (state, { id }) => state.filter((message) => message.id !== id),
                clearQueue: () => [],
            },
        ],
        // Optimistic, client-side only — null means "use the run's stored model/effort". The logic is keyed by
        // `runId`, so switching runs gets a fresh instance with the override reset.
        modelOverride: [
            null as string | null,
            {
                setModel: (_, { model }) => model,
            },
        ],
        effortOverride: [
            null as string | null,
            {
                setEffort: (_, { effort }) => effort,
            },
        ],
        // The model/effort last synced to the agent session via `set_config_option`. null means "not synced
        // yet this session" — the active config is then the run's stored value (or the default).
        sentModel: [
            null as string | null,
            {
                setSentModel: (_, { model }) => model,
            },
        ],
        sentEffort: [
            null as string | null,
            {
                setSentEffort: (_, { effort }) => effort,
            },
        ],
    }),

    forms(({ actions, values }) => ({
        // The composer draft lives here so the input region is a real <form>. `submit` is the single entry
        // point the composer's `onSubmit` calls — it decides send-now vs enqueue vs new-run. It dispatches
        // synchronously (no await), so `isComposerFormSubmitting` isn't the UI loading state — `isSubmitting`
        // (sending || startingRun) is. `errors` gates programmatic `submitComposerForm()`; the UI's own
        // `Composer.Root` disabled-reason is the parallel guard.
        composerForm: {
            defaults: { draft: '' as string },
            errors: ({ draft }) => ({
                draft: !draft.trim() ? 'Type a message first' : undefined,
            }),
            submit: ({ draft }) => {
                const content = draft.trim()
                if (!content) {
                    return
                }
                // A finished run can't take a follow-up signal — send starts a fresh run instead, seeded with
                // this message and chained from the run just viewed.
                if (values.isTerminal) {
                    actions.startNewRun(content)
                    return
                }
                // While the agent is working, a send is in flight, or a message is already staged — concatenate
                // this onto the single queued message so follow-ups never jump ahead or fan out; otherwise send
                // it straight from the draft. `flushQueue` self-guards, draining only when the run is fully idle.
                if (values.isBusy || values.sending || values.queuedMessages.length > 0) {
                    actions.enqueueMessage(content)
                    actions.resetComposerForm()
                    actions.flushQueue()
                } else {
                    actions.sendNow(content, 'draft')
                }
            },
        },
    })),

    selectors({
        isTerminal: [(s) => [s.currentRunStatus], (status): boolean => isTerminalRunStatus(status)],
        // The model/effort to display in the picker and launch the next run with: the optimistic client-side
        // override, else the run's stored value, else the default. Effort is clamped to one the model supports.
        selectedModel: [
            (s) => [s.modelOverride, (_, p) => p.currentModel],
            (override, current): string => override ?? current ?? DEFAULT_COMPOSER_MODEL,
        ],
        selectedEffort: [
            (s) => [s.effortOverride, (_, p) => p.currentEffort, s.selectedModel],
            (override, current, model): ReasoningEffortEnumApi =>
                resolveEffortForModel(override ?? current ?? DEFAULT_COMPOSER_EFFORT, model),
        ],
        // The agent is actively working a turn — a follow-up typed now should stage rather than send.
        isBusy: [(s) => [s.isThinking], (isThinking): boolean => isThinking],
        canSend: [
            (s) => [s.sending, s.isTerminal, s.currentProjectId],
            (sending, isTerminal, currentProjectId): boolean => !sending && !isTerminal && currentProjectId != null,
        ],
        // In-flight indicator for the composer's send button — a live send or a new-run start.
        isSubmitting: [(s) => [s.sending, s.startingRun], (sending, startingRun): boolean => sending || startingRun],
        // Attached context not yet wrapped into a message for this task, the snapshot the next send wraps.
        // The sent-key bookkeeping is task-scoped (`attachedContextLogic.sentContextKeysByTask`), not
        // run-scoped, so the dedupe survives a terminal-run send re-pointing to a fresh run instance.
        // `text` items are never deduped (matches the backend's `prune_repeated_entity_refs`: repeated
        // text is intentional, e.g. consecutive error snippets).
        pendingContextItems: [
            (s) => [s.contextItems, s.sentContextKeysByTask, (_, p: RunInteractionLogicProps) => p.taskId],
            (contextItems, sentContextKeysByTask, taskId): AttachedContextItem[] => {
                const sentKeys = new Set(sentContextKeysByTask[taskId] ?? [])
                return contextItems.filter(
                    (item) => item.type === 'text' || !sentKeys.has(attachedContextItemKey(item))
                )
            },
        ],
    }),

    listeners(({ actions, values, props }) => {
        // Record the non-text refs just wrapped into a send under the task, so no later send anywhere in
        // the task's resume chain (including the next run after a terminal-run send) re-inflates them.
        const markPendingContextSent = (pendingContext: AttachedContextItem[]): void => {
            const sentKeys = pendingContext.filter((item) => item.type !== 'text').map(attachedContextItemKey)
            if (sentKeys.length > 0) {
                actions.markContextSent(props.taskId, sentKeys)
            }
        }

        return {
            // Drain the staged "Up next" message — only when the run is idle and can actually take it, so a flush
            // against a busy/terminal/in-flight send is a no-op rather than dropping the message. The buffer is
            // cleared up-front (not after the send) so a follow-up typed during the in-flight send stages cleanly
            // instead of being wiped along with this send on success; `sendNow` re-stages it if the send fails.
            flushQueue: () => {
                const [queued] = values.queuedMessages
                if (!queued || values.isBusy || !values.canSend) {
                    return
                }
                actions.clearQueue()
                actions.sendNow(queued.content, 'queue')
            },

            sendNow: async ({ content, source }) => {
                if (values.sending || !content.trim() || values.isTerminal || values.currentProjectId == null) {
                    // Nothing was sent. The queue buffer was already cleared in `flushQueue`, so re-stage for
                    // retry; the draft path leaves its content untouched in the composer.
                    if (source === 'queue') {
                        actions.prependQueuedMessage(content)
                    }
                    return
                }
                actions.setSending(true)
                // Clear the draft synchronously before the await so text the user types while the send is in
                // flight isn't clobbered when the request resolves; a failed send restores it ahead of anything
                // typed since. The queue buffer was already cleared up-front in `flushQueue`.
                if (source === 'draft') {
                    actions.resetComposerForm()
                }
                try {
                    // Sync the picked model/effort to the agent session first, but only what the user actually
                    // changed since the last sync — mid-run config lives as session state, so it must go via a
                    // `set_config_option` command before the message rather than ride inside `user_message`. A
                    // failure here aborts the send (the catch restores the content); `setSent*` runs only after a
                    // successful sync so the next send retries an unsent change.
                    const activeModel = values.sentModel ?? props.currentModel ?? DEFAULT_COMPOSER_MODEL
                    const activeEffort = resolveEffortForModel(
                        values.sentEffort ?? props.currentEffort ?? DEFAULT_COMPOSER_EFFORT,
                        activeModel
                    )
                    if (values.selectedModel !== activeModel) {
                        await tasksRunsCommandCreate(String(values.currentProjectId), props.taskId, props.runId, {
                            jsonrpc: '2.0',
                            method: 'set_config_option',
                            params: { configId: MODEL_CONFIG_ID, value: values.selectedModel },
                        })
                        actions.setSentModel(values.selectedModel)
                    }
                    if (values.selectedEffort !== activeEffort) {
                        await tasksRunsCommandCreate(String(values.currentProjectId), props.taskId, props.runId, {
                            jsonrpc: '2.0',
                            method: 'set_config_option',
                            params: { configId: EFFORT_CONFIG_ID, value: values.selectedEffort },
                        })
                        actions.setSentEffort(values.selectedEffort)
                    }
                    // Wrap the outgoing content with the on-screen context block (invisible to the user —
                    // `runStreamLogic.unwrapUserMessageContent` strips it on replay, and the echo below is raw).
                    const pendingContext = values.pendingContextItems
                    await tasksRunsCommandCreate(String(values.currentProjectId), props.taskId, props.runId, {
                        jsonrpc: '2.0',
                        method: 'user_message',
                        params: { content: wrapWithPosthogContext(content, pendingContext) },
                    })
                    // The SSE echo (`pushHumanMessage`) reopens the turn — always the raw text the user typed.
                    actions.pushHumanMessage(content)
                    markPendingContextSent(pendingContext)
                } catch {
                    // Restore unsent content for retry, preserving send order — draft content goes back ahead of
                    // anything typed during the failed send, queue content re-stages ahead of anything staged since.
                    if (source === 'draft') {
                        actions.setComposerFormValues({
                            draft: values.composerForm.draft ? `${content}\n\n${values.composerForm.draft}` : content,
                        })
                    } else {
                        actions.prependQueuedMessage(content)
                    }
                    lemonToast.error('Failed to send message. Please try again.')
                } finally {
                    actions.setSending(false)
                }
            },

            // The agent finished a turn — drain any staged follow-ups.
            markTurnComplete: () => {
                actions.flushQueue()
            },

            // The new model may not support the current effort — clamp the override so it never holds an
            // unsupported value. No network here: the pick is synced to the agent at send time.
            setModel: ({ model }) => {
                const currentEffort = values.effortOverride ?? props.currentEffort
                const resolvedEffort = resolveEffortForModel(currentEffort, model)
                if (resolvedEffort !== currentEffort) {
                    actions.setEffort(resolvedEffort)
                }
            },

            startNewRun: async ({ content }) => {
                if (values.startingRun || !content.trim() || values.currentProjectId == null) {
                    return
                }
                actions.setStartingRun(true)
                try {
                    // Same endpoint as the "Run again" button, but seeded with the user's message and chained
                    // from the finished run so the new run continues the thread, and carrying the picked model /
                    // reasoning effort (the resume schema can't, so we send the Claude create shape). The response
                    // carries the new run id as `latest_run`; the consumer-provided `onRunStarted` re-points to it.
                    const pendingContext = values.pendingContextItems
                    const createRequest: ClaudeTaskRunCreateSchemaApi = {
                        runtime_adapter: ClaudeRuntimeAdapterEnumApi.Claude,
                        model: values.selectedModel,
                        reasoning_effort: values.selectedEffort,
                        resume_from_run_id: props.runId,
                        pending_user_message: wrapWithPosthogContext(content, pendingContext),
                    }
                    const result = await tasksRunCreate(String(values.currentProjectId), props.taskId, createRequest)
                    actions.resetComposerForm()
                    markPendingContextSent(pendingContext)
                    if (result.latest_run) {
                        props.onRunStarted?.(result.latest_run)
                    }
                } catch {
                    lemonToast.error('Failed to start a new run. Please try again.')
                } finally {
                    actions.setStartingRun(false)
                }
            },
        }
    }),
])
