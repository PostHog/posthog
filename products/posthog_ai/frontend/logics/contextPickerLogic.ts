import { actions, connect, events, kea, listeners, path, reducers, selectors, sharedListeners } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { type AttachedContextItem, attachedContextItemKey } from '../types/contextTypes'
import { attachedContextLogic } from './attachedContextLogic'
import type { contextPickerLogicType } from './contextPickerLogicType'

export const PICKER_PROVIDER_ID = 'user-picker'

/** Structural subset of the taxonomic item shapes the picker consumes — no scene-tree type imports. */
export interface PickableTaxonomicItem {
    id?: string | number
    short_id?: string
    name?: string | null
    title?: string | null
}

/**
 * Projects a TaxonomicFilter selection down to the surface's abstract `AttachedContextItem`.
 * Refs only — no entity loading; the agent fetches details via its read tools.
 * Returns null for group types the picker doesn't offer.
 */
export function taxonomicItemToAttachedContext(
    value: string | number,
    groupType: TaxonomicFilterGroupType,
    item: PickableTaxonomicItem
): AttachedContextItem | null {
    switch (groupType) {
        case TaxonomicFilterGroupType.Events:
            return { type: 'event', key: item.id ?? item.name ?? value, label: item.name ?? undefined }
        case TaxonomicFilterGroupType.Actions:
            return { type: 'action', key: item.id ?? value, label: item.name ?? undefined }
        case TaxonomicFilterGroupType.Insights:
            return { type: 'insight', key: item.short_id ?? value, label: item.name ?? undefined }
        case TaxonomicFilterGroupType.Dashboards:
            return { type: 'dashboard', key: item.id ?? value, label: item.name ?? undefined }
        case TaxonomicFilterGroupType.Notebooks:
            return { type: 'notebook', key: item.short_id ?? value, label: item.title ?? undefined }
        case TaxonomicFilterGroupType.ErrorTrackingIssues:
            return { type: 'error_tracking_issue', key: item.id ?? value, label: item.name ?? undefined }
        default:
            return null
    }
}

/**
 * Global store of context the user explicitly picked via the composer's @-affordance. Just another
 * provider on `attachedContextLogic` (id `user-picker`): picks upsert into `pickedItems`, and every
 * change re-registers the provider, so picked refs flow into `contextItems` and the send-time
 * `<posthog_context>` wrap with zero extra plumbing.
 */
export const contextPickerLogic = kea<contextPickerLogicType>([
    path(['products', 'posthog_ai', 'frontend', 'logics', 'contextPickerLogic']),

    connect(() => ({
        actions: [attachedContextLogic, ['registerContext', 'deregisterContext', 'undismissContext']],
    })),

    actions({
        /** Signature matches `TaxonomicPopover.onChange` so the component can pass it straight through. */
        handleTaxonomicFilterChange: (
            value: string | number,
            groupType: TaxonomicFilterGroupType,
            item: PickableTaxonomicItem
        ) => ({ value, groupType, item }),
        pickItem: (item: AttachedContextItem) => ({ item }),
        removePickedItem: (key: string) => ({ key }),
        clearPickedItems: true,
    }),

    reducers({
        pickedItems: [
            [] as AttachedContextItem[],
            {
                pickItem: (state, { item }) => {
                    const key = attachedContextItemKey(item)
                    return state.filter((existing) => attachedContextItemKey(existing) !== key).concat(item)
                },
                removePickedItem: (state, { key }) =>
                    state.filter((existing) => attachedContextItemKey(existing) !== key),
                clearPickedItems: () => [],
            },
        ],
    }),

    selectors({
        pickedKeys: [
            (s) => [s.pickedItems],
            (pickedItems): Set<string> => new Set(pickedItems.map(attachedContextItemKey)),
        ],
    }),

    sharedListeners(({ actions, values }) => ({
        syncProvider: () => {
            actions.registerContext(PICKER_PROVIDER_ID, values.pickedItems)
        },
    })),

    listeners(({ actions, sharedListeners }) => ({
        handleTaxonomicFilterChange: ({ value, groupType, item }) => {
            const attached = taxonomicItemToAttachedContext(value, groupType, item)
            if (!attached) {
                return
            }
            // Re-picking something the user previously closed must bring it back.
            actions.undismissContext(attachedContextItemKey(attached))
            actions.pickItem(attached)
        },
        pickItem: sharedListeners.syncProvider,
        removePickedItem: sharedListeners.syncProvider,
        clearPickedItems: sharedListeners.syncProvider,
    })),

    events(({ actions, cache, values }) => ({
        afterMount: () => {
            // `pauseOnPageHidden: false`: a hide-paused registration would drop picked context from a
            // queued follow-up that flushes while the tab is hidden; the registration is idle-cost-free.
            cache.disposables.add(
                () => {
                    actions.registerContext(PICKER_PROVIDER_ID, values.pickedItems)
                    return () => actions.deregisterContext(PICKER_PROVIDER_ID)
                },
                'contextPicker',
                { pauseOnPageHidden: false }
            )
        },
    })),
])
