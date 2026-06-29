import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

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

import type { runInteractionLogicType } from './runInteractionLogicType'
import { isTerminalRunStatus, runStreamLogic } from './runStreamLogic'

export interface RunInteractionLogicProps {
    taskId: string
    runId: string
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
            runStreamLogic({ streamKey: props.runId }),
            ['currentRunStatus', 'pendingPermissionRequest', 'respondingToPermission', 'isThinking'],
        ],
        actions: [
            runStreamLogic({ streamKey: props.runId }),
            ['pushHumanMessage', 'respondToPermission', 'cancelRun', 'markTurnComplete'],
        ],
    })),

    actions({
        setDraft: (draft: string) => ({ draft }),
        clearDraft: true,
        // Single entry point the composer's `onSubmit` calls — decides send-now vs enqueue vs new-run.
        submit: true,
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
        // Live-switch the running agent's model / reasoning effort via a `set_config_option` command. The
        // override is held client-side (the backend doesn't persist live changes back to the run state).
        setModel: (model: string) => ({ model }),
        setEffort: (effort: string) => ({ effort }),
        // Internal: drop the optimistic override (e.g. the command failed) so the display falls back to the
        // run's stored value.
        resetModelOverride: true,
        resetEffortOverride: true,
    }),

    reducers({
        draft: [
            '',
            {
                setDraft: (_, { draft }) => draft,
                clearDraft: () => '',
            },
        ],
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
                resetModelOverride: () => null,
            },
        ],
        effortOverride: [
            null as string | null,
            {
                setEffort: (_, { effort }) => effort,
                resetEffortOverride: () => null,
            },
        ],
    }),

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
    }),

    listeners(({ actions, values, props }) => ({
        submit: () => {
            const content = values.draft.trim()
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
            // this onto the single queued message so follow-ups never jump ahead or fan out; otherwise send it
            // straight from the draft. `flushQueue` self-guards, draining only when the run is fully idle.
            if (values.isBusy || values.sending || values.queuedMessages.length > 0) {
                actions.enqueueMessage(content)
                actions.clearDraft()
                actions.flushQueue()
            } else {
                actions.sendNow(content, 'draft')
            }
        },

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
                actions.clearDraft()
            }
            try {
                await tasksRunsCommandCreate(String(values.currentProjectId), props.taskId, props.runId, {
                    jsonrpc: '2.0',
                    method: 'user_message',
                    params: { content },
                })
                // The SSE echo (`pushHumanMessage`) reopens the turn.
                actions.pushHumanMessage(content)
            } catch {
                // Restore unsent content for retry, preserving send order — draft content goes back ahead of
                // anything typed during the failed send, queue content re-stages ahead of anything staged since.
                if (source === 'draft') {
                    actions.setDraft(values.draft ? `${content}\n\n${values.draft}` : content)
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

        setModel: async ({ model }) => {
            if (values.isTerminal || values.currentProjectId == null) {
                return
            }
            try {
                await tasksRunsCommandCreate(String(values.currentProjectId), props.taskId, props.runId, {
                    jsonrpc: '2.0',
                    method: 'set_config_option',
                    params: { configId: MODEL_CONFIG_ID, value: model },
                })
            } catch {
                actions.resetModelOverride()
                lemonToast.error('Failed to switch model. Please try again.')
            }
        },

        setEffort: async ({ effort }) => {
            if (values.isTerminal || values.currentProjectId == null) {
                return
            }
            try {
                await tasksRunsCommandCreate(String(values.currentProjectId), props.taskId, props.runId, {
                    jsonrpc: '2.0',
                    method: 'set_config_option',
                    params: { configId: EFFORT_CONFIG_ID, value: effort },
                })
            } catch {
                actions.resetEffortOverride()
                lemonToast.error('Failed to switch effort. Please try again.')
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
                const createRequest: ClaudeTaskRunCreateSchemaApi = {
                    runtime_adapter: ClaudeRuntimeAdapterEnumApi.Claude,
                    model: values.selectedModel,
                    reasoning_effort: values.selectedEffort,
                    resume_from_run_id: props.runId,
                    pending_user_message: content,
                }
                const result = await tasksRunCreate(String(values.currentProjectId), props.taskId, createRequest)
                actions.clearDraft()
                if (result.latest_run) {
                    props.onRunStarted?.(result.latest_run)
                }
            } catch {
                lemonToast.error('Failed to start a new run. Please try again.')
            } finally {
                actions.setStartingRun(false)
            }
        },
    })),
])
