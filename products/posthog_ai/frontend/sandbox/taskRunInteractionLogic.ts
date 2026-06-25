import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { projectLogic } from 'scenes/projectLogic'

import { tasksRunCreate, tasksRunsCommandCreate } from 'products/tasks/frontend/generated/api'
import type { TaskRunResumeRequestSchemaApi } from 'products/tasks/frontend/generated/api.schemas'

import { isTerminalRunStatus, sandboxStreamLogic } from './sandboxStreamLogic'
import type { taskRunInteractionLogicType } from './taskRunInteractionLogicType'

export interface TaskRunInteractionLogicProps {
    taskId: string
    runId: string
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

/**
 * Max-agnostic interaction facade for a single task run. The UI binds to this one logic to drive every
 * user → run interaction — sending follow-ups, staging an editable "Up next" message while the agent is
 * busy, and (re-exposed from `sandboxStreamLogic`) answering questions / approving operations. It owns no
 * transport: the SSE stream, thread projection, run status, and permission routing all live in
 * `sandboxStreamLogic`, which this connects to by `streamKey` (the `runId`).
 *
 * Queueing is client-side and holds at most a single message: a follow-up typed while the agent is working
 * a turn is staged here (editable, removable), and a second follow-up typed before the turn ends is
 * concatenated onto it rather than fanning out into separate messages. The single staged message is flushed
 * as one `user_message` when the turn completes. This mirrors the PostHog AI sandbox flush path without any
 * conversation/Max coupling.
 */
export const taskRunInteractionLogic = kea<taskRunInteractionLogicType>([
    path(['products', 'posthog_ai', 'frontend', 'sandbox', 'taskRunInteractionLogic']),
    props({} as TaskRunInteractionLogicProps),
    key((props) => props.runId),

    connect((props: TaskRunInteractionLogicProps) => ({
        values: [
            projectLogic,
            ['currentProjectId'],
            sandboxStreamLogic({ streamKey: props.runId }),
            ['currentRunStatus', 'pendingPermissionRequest', 'respondingToPermission', 'isThinking'],
        ],
        actions: [
            sandboxStreamLogic({ streamKey: props.runId }),
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
        updateQueuedMessage: (id: string, content: string) => ({ id, content }),
        removeQueuedMessage: (id: string) => ({ id }),
        clearQueue: true,
        // Internal: drain the staged "Up next" message when the agent is idle.
        flushQueue: true,
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
                updateQueuedMessage: (state, { id, content }) =>
                    state.map((message) => (message.id === id ? { ...message, content } : message)),
                removeQueuedMessage: (state, { id }) => state.filter((message) => message.id !== id),
                clearQueue: () => [],
            },
        ],
    }),

    selectors({
        isTerminal: [(s) => [s.currentRunStatus], (status): boolean => isTerminalRunStatus(status)],
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
            // While the agent is working — or a message is already staged — concatenate this onto the single
            // queued message so follow-ups never jump ahead or fan out; otherwise send it straight from the
            // draft. When idle with a staged message, drain right away so it doesn't linger.
            if (values.isBusy || values.queuedMessages.length > 0) {
                actions.enqueueMessage(content)
                actions.clearDraft()
                if (!values.isBusy) {
                    actions.flushQueue()
                }
            } else {
                actions.sendNow(content, 'draft')
            }
        },

        // Drain the staged "Up next" message — but only when the run can actually take it, so a flush against
        // a terminal/in-flight send keeps it rather than dropping it. The queue is cleared by `sendNow` on
        // success, not here, so a failed flush retains the message.
        flushQueue: () => {
            const [queued] = values.queuedMessages
            if (!queued || !values.canSend) {
                return
            }
            actions.sendNow(queued.content, 'queue')
        },

        sendNow: async ({ content, source }) => {
            if (values.sending || !content.trim() || values.isTerminal || values.currentProjectId == null) {
                return
            }
            actions.setSending(true)
            try {
                await tasksRunsCommandCreate(String(values.currentProjectId), props.taskId, props.runId, {
                    jsonrpc: '2.0',
                    method: 'user_message',
                    params: { content },
                })
                // The SSE echo (`pushHumanMessage`) reopens the turn. Clear the source only on success so a
                // failed send keeps the user's text (in the composer or the queue) for retry.
                actions.pushHumanMessage(content)
                if (source === 'draft') {
                    actions.clearDraft()
                } else {
                    actions.clearQueue()
                }
            } catch {
                lemonToast.error('Failed to send message. Please try again.')
            } finally {
                actions.setSending(false)
            }
        },

        // The agent finished a turn — drain any staged follow-ups.
        markTurnComplete: () => {
            actions.flushQueue()
        },

        startNewRun: async ({ content }) => {
            if (values.startingRun || !content.trim() || values.currentProjectId == null) {
                return
            }
            actions.setStartingRun(true)
            try {
                // Same endpoint as the "Run again" button, but seeded with the user's message and chained
                // from the finished run so the new run continues the thread. The response carries the new
                // run id as `latest_run`; the consumer-provided `onRunStarted` re-points selection to it.
                const resumeRequest: TaskRunResumeRequestSchemaApi = {
                    resume_from_run_id: props.runId,
                    pending_user_message: content,
                }
                const result = await tasksRunCreate(String(values.currentProjectId), props.taskId, resumeRequest)
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
