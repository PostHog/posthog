import { actions, kea, path, reducers, selectors } from 'kea'

import { type AttachedContextItem, attachedContextItemKey } from '../types/contextTypes'
import type { attachedContextLogicType } from './attachedContextLogicType'

/**
 * Global, unkeyed store of attached context for the PostHog AI surface. One mechanism only — a
 * registry of context providers, so registration and removal are symmetric and trivial. Each
 * provider (a mounted hook/component, or a future @-mention picker) owns a stable `providerId` and
 * upserts its items; `contextItems` flattens and dedupes across providers.
 *
 * A consumer reads `contextItems` at send time and wraps the outgoing message with a
 * `<posthog_context>` block (`utils/posthogContextBlock`). Nothing here is keyed by conversation —
 * the on-screen context is global to the app at any instant.
 *
 * This store also keeps the sent-context bookkeeping (`sentContextKeysByTask`): which non-text refs
 * were already wrapped into a sent message, keyed by task id. The send paths mark keys after a
 * successful send and prune already-sent refs from the next wrap. It is task-scoped (not run-scoped)
 * so the dedupe survives a terminal-run send re-pointing the consumer to a fresh run, mirroring the
 * backend's `prune_repeated_entity_refs`, which dedupes across a task's whole resume chain.
 */
export const attachedContextLogic = kea<attachedContextLogicType>([
    path(['products', 'posthog_ai', 'frontend', 'logics', 'attachedContextLogic']),

    actions({
        /** Idempotent upsert — re-register the same `providerId` to update its items. */
        registerContext: (providerId: string, items: AttachedContextItem[]) => ({ providerId, items }),
        deregisterContext: (providerId: string) => ({ providerId }),
        /** Record context item keys already wrapped into a message sent for `taskId`. */
        markContextSent: (taskId: string, keys: string[]) => ({ taskId, keys }),
    }),

    reducers({
        providers: [
            {} as Record<string, AttachedContextItem[]>,
            {
                registerContext: (state, { providerId, items }) => ({ ...state, [providerId]: items }),
                deregisterContext: (state, { providerId }) => {
                    if (!(providerId in state)) {
                        return state
                    }
                    const { [providerId]: _dropped, ...rest } = state
                    return rest
                },
            },
        ],
        // Per-task set of `attachedContextItemKey`s already wrapped into a sent message. Append-only for
        // the session: entity refs sent once anywhere in a task's resume chain stay pruned from later sends.
        sentContextKeysByTask: [
            {} as Record<string, string[]>,
            {
                markContextSent: (state, { taskId, keys }) => {
                    if (keys.length === 0) {
                        return state
                    }
                    const existing = state[taskId] ?? []
                    const added = keys.filter((key) => !existing.includes(key))
                    if (added.length === 0) {
                        return state
                    }
                    return { ...state, [taskId]: [...existing, ...added] }
                },
            },
        ],
    }),

    selectors({
        // Flattened across providers, deduped by `${type}:${key ?? value}` (first writer wins).
        // Items with neither `key` nor `value` carry no payload and are dropped.
        contextItems: [
            (s) => [s.providers],
            (providers): AttachedContextItem[] => {
                const seen = new Set<string>()
                const out: AttachedContextItem[] = []
                for (const items of Object.values(providers)) {
                    for (const item of items) {
                        const hasKey = item.key !== undefined && item.key !== null && item.key !== ''
                        const hasValue = item.value !== undefined && item.value !== ''
                        if (!hasKey && !hasValue) {
                            continue
                        }
                        const key = attachedContextItemKey(item)
                        if (seen.has(key)) {
                            continue
                        }
                        seen.add(key)
                        out.push(item)
                    }
                }
                return out
            },
        ],
        hasContext: [(s) => [s.contextItems], (contextItems): boolean => contextItems.length > 0],
    }),
])
