import { actions, kea, listeners, path, reducers } from 'kea'
import posthog from 'posthog-js'

import type { ToolStreamEvent } from '../types/streamTypes'
import type { toolStreamEventsLogicType } from './toolStreamEventsLogicType'

export interface ToolStreamSubscription {
    /** Resolved tool names to match, or `'*'` for every tool. */
    tools: string[] | '*'
    onEvent: (event: ToolStreamEvent) => void
    /** When true, replay-sourced events are delivered too. Defaults to false (live only). */
    includeReplay?: boolean
}

function subscriptionMatches(subscription: ToolStreamSubscription, event: ToolStreamEvent): boolean {
    if (event.source === 'replay' && !subscription.includeReplay) {
        return false
    }
    if (subscription.tools === '*') {
        return true
    }
    return subscription.tools.includes(event.toolName)
}

/**
 * Global, unkeyed event bus for tool-call lifecycle events. `runStreamLogic` emits `ToolStreamEvent`s
 * (with resolved tool names); consumers register a listener that fires their `onEvent` for matching
 * tools. Callbacks live in reducer state — the same precedent as `maxGlobalLogic.toolMap`. Replay
 * events are suppressed unless a subscription opts in via `includeReplay`.
 *
 * Kea-native alternative: `connect` to this bus and add
 * `listeners({ [toolStreamEventsLogic.actionTypes.emitToolEvent]: ({ event }) => ... })`.
 */
export const toolStreamEventsLogic = kea<toolStreamEventsLogicType>([
    path(['products', 'posthog_ai', 'frontend', 'logics', 'toolStreamEventsLogic']),

    actions({
        emitToolEvent: (event: ToolStreamEvent) => ({ event }),
        registerToolListener: (listenerId: string, subscription: ToolStreamSubscription) => ({
            listenerId,
            subscription,
        }),
        deregisterToolListener: (listenerId: string) => ({ listenerId }),
    }),

    reducers({
        toolListeners: [
            {} as Record<string, ToolStreamSubscription>,
            {
                registerToolListener: (state, { listenerId, subscription }) => ({
                    ...state,
                    [listenerId]: subscription,
                }),
                deregisterToolListener: (state, { listenerId }) => {
                    if (!(listenerId in state)) {
                        return state
                    }
                    const { [listenerId]: _dropped, ...rest } = state
                    return rest
                },
            },
        ],
    }),

    listeners(({ values }) => ({
        emitToolEvent: ({ event }) => {
            for (const subscription of Object.values(values.toolListeners)) {
                if (!subscriptionMatches(subscription, event)) {
                    continue
                }
                // The emit is dispatched synchronously from `runStreamLogic`'s frame ingestion — one
                // throwing subscriber must not break the stream (or starve later subscribers).
                try {
                    subscription.onEvent(event)
                } catch (error) {
                    posthog.captureException(error, { feature: 'posthog_ai_tool_stream_listener' })
                }
            }
        },
    })),
])

/** Whether any registered listener wants replay events — a cheap guard so `runStreamLogic` skips
 * per-frame resolution during history replay when nobody is listening for it. */
export function hasReplayListener(toolListeners: Record<string, ToolStreamSubscription>): boolean {
    return Object.values(toolListeners).some((subscription) => subscription.includeReplay)
}
