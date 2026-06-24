import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { projectLogic } from 'scenes/projectLogic'

import { tasksRunsCommandCreate } from 'products/tasks/frontend/generated/api'

import { isTerminalRunStatus, sandboxStreamLogic } from './sandboxStreamLogic'
import type { taskRunInteractionLogicType } from './taskRunInteractionLogicType'

export interface TaskRunInteractionLogicProps {
    taskId: string
    runId: string
}

/** A follow-up message staged in the "Up next" buffer while the agent is mid-turn. */
export interface QueuedMessage {
    id: string
    content: string
}

/** Cap on staged "Up next" messages, mirroring the Max queue limit. */
const QUEUE_LIMIT = 10

/**
 * Max-agnostic interaction facade for a single task run. The UI binds to this one logic to drive every
 * user → run interaction — sending follow-ups, staging an editable "Up next" queue while the agent is
 * busy, and (re-exposed from `sandboxStreamLogic`) answering questions / approving operations. It owns no
 * transport: the SSE stream, thread projection, run status, and permission routing all live in
 * `sandboxStreamLogic`, which this connects to by `streamKey` (the `runId`).
 *
 * Queueing is client-side: a follow-up typed while the agent is working a turn is held here (editable,
 * removable) and flushed — combined into one `user_message` — when the turn completes. This mirrors the
 * PostHog AI sandbox flush path without any conversation/Max coupling.
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
        // Single entry point the composer's `onSubmit` calls — decides send-now vs enqueue.
        submit: true,
        setSending: (sending: boolean) => ({ sending }),
        // Internal: POST one `user_message` now. `source` says where the content lives so a successful send
        // clears the right place and a failed send preserves it for retry ('draft' → composer, 'queue' →
        // the staged buffer combined into this send).
        sendNow: (content: string, source: 'draft' | 'queue') => ({ content, source }),
        enqueueMessage: (content: string, id: string) => ({ content, id }),
        updateQueuedMessage: (id: string, content: string) => ({ id, content }),
        removeQueuedMessage: (id: string) => ({ id }),
        clearQueue: true,
        // Internal: drain the "Up next" buffer (combined) when the agent is idle.
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
        queuedMessages: [
            [] as QueuedMessage[],
            {
                enqueueMessage: (state, { content, id }) => [...state, { id, content }],
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
        queueFull: [(s) => [s.queuedMessages], (queuedMessages): boolean => queuedMessages.length >= QUEUE_LIMIT],
    }),

    listeners(({ actions, values, props, cache }) => ({
        submit: () => {
            const content = values.draft.trim()
            if (!content || values.queueFull || values.isTerminal) {
                return
            }
            // While the agent is working — or there are already staged messages — hold this one in the
            // queue so it can't jump ahead; otherwise send it straight from the draft. When idle with a
            // non-empty queue, drain right away so the staged messages don't linger.
            if (values.isBusy || values.queuedMessages.length > 0) {
                cache.queueSeq = (cache.queueSeq ?? 0) + 1
                actions.enqueueMessage(content, String(cache.queueSeq))
                actions.clearDraft()
                if (!values.isBusy) {
                    actions.flushQueue()
                }
            } else {
                actions.sendNow(content, 'draft')
            }
        },

        // Drain the "Up next" buffer as one combined message — but only when the run can actually take it,
        // so a flush against a terminal/in-flight send keeps the staged messages rather than dropping them.
        // The queue is cleared by `sendNow` on success, not here, so a failed flush retains the messages.
        flushQueue: () => {
            if (values.queuedMessages.length === 0 || !values.canSend) {
                return
            }
            const combined = values.queuedMessages.map((message) => message.content).join('\n\n')
            actions.sendNow(combined, 'queue')
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
    })),
])
