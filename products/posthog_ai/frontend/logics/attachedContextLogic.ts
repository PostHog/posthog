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
 */
export const attachedContextLogic = kea<attachedContextLogicType>([
    path(['products', 'posthog_ai', 'frontend', 'logics', 'attachedContextLogic']),

    actions({
        /** Idempotent upsert — re-register the same `providerId` to update its items. */
        registerContext: (providerId: string, items: AttachedContextItem[]) => ({ providerId, items }),
        deregisterContext: (providerId: string) => ({ providerId }),
        /**
         * Hide one item (by `attachedContextItemKey`) regardless of which provider contributed it —
         * the user closing a chip must stick even when the provider re-registers the same item
         * (e.g. the scene bridge upserting on every scene read).
         */
        dismissContext: (key: string) => ({ key }),
        undismissContext: (key: string) => ({ key }),
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
        dismissedKeys: [
            {} as Record<string, true>,
            {
                dismissContext: (state, { key }) => ({ ...state, [key]: true as const }),
                undismissContext: (state, { key }) => {
                    if (!(key in state)) {
                        return state
                    }
                    const { [key]: _dropped, ...rest } = state
                    return rest
                },
            },
        ],
    }),

    selectors({
        // Flattened across providers, deduped by `${type}:${key ?? value}` (first writer wins).
        // Items with neither `key` nor `value` carry no payload and are dropped, as are dismissed keys.
        contextItems: [
            (s) => [s.providers, s.dismissedKeys],
            (providers, dismissedKeys): AttachedContextItem[] => {
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
                        if (seen.has(key) || dismissedKeys[key]) {
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
