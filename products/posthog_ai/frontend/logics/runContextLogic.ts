import { actions, kea, key, path, props, reducers, selectors } from 'kea'

import type { AgentContextChip, AgentContextItem } from '../types/contextTypes'
import { agentContextKey } from '../types/contextTypes'
import type { runContextLogicType } from './runContextLogicType'

export interface RunContextLogicProps {
    /** Same key `runStreamLogic` uses — conversation id for Max, run/task id for a task viewer. */
    streamKey: string
}

/** The imperative `attach`/`detach` bucket, reserved so it never collides with a registered source id. */
const IMPERATIVE_SOURCE = 'imperative'

/**
 * Merge every source's items into one deduped list, first-seen wins per `agentContextKey`. `text`
 * items pass through untouched (repeated text is intentional). Iteration order is object-insertion
 * order, so the merge is deterministic for a given write sequence.
 */
function mergeSources(sources: Record<string, AgentContextItem[]>): AgentContextItem[] {
    const merged: AgentContextItem[] = []
    const seen = new Set<string>()
    for (const items of Object.values(sources)) {
        for (const item of items) {
            if (item.type === 'text') {
                merged.push(item)
                continue
            }
            const key = agentContextKey(item)
            if (seen.has(key)) {
                continue
            }
            seen.add(key)
            merged.push(item)
        }
    }
    return merged
}

function labelForItem(item: AgentContextItem): string {
    if (item.type === 'text') {
        return item.value ?? 'Text'
    }
    return item.name ?? `${item.type} ${item.id ?? ''}`.trim()
}

/**
 * Generic frontend context store for the agent-run surface, keyed by `streamKey`.
 *
 * Multi-source by design so several writers contribute without clobbering each other: a writer owns a
 * named `sourceId` bucket (register-on-mount / deregister-on-unmount via `useAgentContext`), and the
 * imperative `attach`/`detach` affordances accumulate in a reserved `'imperative'` bucket. The merged,
 * deduped `attachedContext` is what a send path forwards as `attached_context`.
 *
 * Runtime-agnostic and Max-free — Max's scene-pull writer registers into this as one more source.
 */
export const runContextLogic = kea<runContextLogicType>([
    props({} as RunContextLogicProps),
    key((props) => props.streamKey),
    path((key) => ['products', 'posthog_ai', 'frontend', 'logics', 'runContextLogic', key]),

    actions({
        /** Register (or replace) a named source's full item list. Idempotent on re-register. */
        registerContextSource: (sourceId: string, items: AgentContextItem[]) => ({ sourceId, items }),
        /** Drop a named source's items (e.g. its writer unmounted). */
        deregisterContextSource: (sourceId: string) => ({ sourceId }),
        /** Dedup-add a single item to the imperative bucket (e.g. a TaxonomicFilter "attach" affordance). */
        attach: (item: AgentContextItem) => ({ item }),
        /** Remove an imperatively-attached item by its `agentContextKey`. */
        detach: (key: string) => ({ key }),
        /** Clear everything — every source and the imperative bucket. */
        clear: true,
    }),

    reducers({
        sources: [
            {} as Record<string, AgentContextItem[]>,
            {
                registerContextSource: (state, { sourceId, items }) => ({ ...state, [sourceId]: items }),
                deregisterContextSource: (state, { sourceId }) => {
                    if (!(sourceId in state)) {
                        return state
                    }
                    const next = { ...state }
                    delete next[sourceId]
                    return next
                },
                attach: (state, { item }) => {
                    const bucket = state[IMPERATIVE_SOURCE] ?? []
                    // Text items are never deduped — repeated text is intentional.
                    if (item.type !== 'text' && bucket.some((e) => agentContextKey(e) === agentContextKey(item))) {
                        return state
                    }
                    return { ...state, [IMPERATIVE_SOURCE]: [...bucket, item] }
                },
                detach: (state, { key }) => {
                    const bucket = state[IMPERATIVE_SOURCE]
                    if (!bucket) {
                        return state
                    }
                    return { ...state, [IMPERATIVE_SOURCE]: bucket.filter((item) => agentContextKey(item) !== key) }
                },
                clear: () => ({}),
            },
        ],
    }),

    selectors({
        attachedContext: [
            (s) => [s.sources],
            (sources: Record<string, AgentContextItem[]>): AgentContextItem[] => mergeSources(sources),
        ],
        // Instance-agnostic chip data — no onRemove closures. Removal dispatches `detach(key)` on the
        // consumer's bound instance, and icons stay in React (the consumer maps `type` → icon).
        chipsForDisplay: [
            (s) => [s.attachedContext],
            (attachedContext: AgentContextItem[]): AgentContextChip[] =>
                attachedContext.map((item) => ({
                    key: agentContextKey(item),
                    label: labelForItem(item),
                    type: item.type,
                })),
        ],
    }),
])
