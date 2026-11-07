import { useActions, useValues } from 'kea'

import { inboxSourceFilterLabel } from '../../filterOptions'
import { InboxSourceSelection, inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { scoutFleetLogic } from '../../logics/scoutFleetLogic'
import { signalSourcesLogic } from '../../signalSourcesLogic'
import { InboxSourceChoice, buildInboxSourceChoices, singleInboxSourceSelection } from '../../utils/inboxSourceFilter'

export const INBOX_SOURCE_UNAVAILABLE_REASON = 'This is no longer configured on this project'

export const INBOX_ALL_SOURCES_LABEL = inboxSourceFilterLabel([])
export const INBOX_SOURCE_SEARCH_PLACEHOLDER = 'Search sources and scouts'

export const INBOX_SOURCE_GROUP_TITLE = { source_product: 'Sources', scout: 'Scouts' } as const

export function inboxSourceEmptyText(kind: InboxSourceSelection['kind'], searching: boolean): string {
    if (kind === 'scout') {
        return searching ? 'No matching scouts' : 'No scouts configured'
    }
    return searching ? 'No matching sources' : 'No sources configured'
}

export function sameInboxSourceSelection(a: InboxSourceSelection | null, b: InboxSourceSelection): boolean {
    return !!a && a.kind === b.kind && a.value === b.value
}

export interface InboxSourceChoiceList {
    choices: InboxSourceChoice[]
    loading: boolean
    failed: boolean
    retry: () => void
}

export interface InboxSourceFilterState {
    sources: InboxSourceChoiceList
    scouts: InboxSourceChoiceList
    selection: InboxSourceSelection | null
    hasSelection: boolean
    label: string
    /** Loads the source configs the first time the picker opens. */
    ensureSourceConfigs: () => void
    setSourceFilter: (selection: InboxSourceSelection | null) => void
}

/**
 * The Source filter's choices and label: one configured product, or one scout. The choices come from
 * the source and scout configs, not from the loaded reports, so every page is reachable.
 */
export function useInboxSourceFilter(): InboxSourceFilterState {
    const { sourceProductFilter, scoutFilter } = useValues(inboxFiltersLogic)
    const { setSourceFilter } = useActions(inboxFiltersLogic)
    const { sourceConfigs, sourceConfigsLoading } = useValues(signalSourcesLogic)
    const { loadSourceConfigs } = useActions(signalSourcesLogic)
    const { scoutConfigs, scoutConfigsLoading } = useValues(scoutFleetLogic)
    const { loadScoutConfigs } = useActions(scoutFleetLogic)

    const { sources, scouts } = buildInboxSourceChoices({
        sourceConfigs,
        scoutConfigs,
        sourceProductFilter,
        scoutFilter,
    })
    const selection = singleInboxSourceSelection(sourceProductFilter, scoutFilter)
    const selectedChoice = selection
        ? [...sources, ...scouts].find((choice) => sameInboxSourceSelection(selection, choice))
        : undefined
    const label = !selectedChoice
        ? inboxSourceFilterLabel(sourceProductFilter, scoutFilter)
        : selectedChoice.kind === 'scout'
          ? `Scout · ${selectedChoice.label}`
          : selectedChoice.label

    return {
        sources: {
            choices: sources,
            loading: sourceConfigs === null && sourceConfigsLoading,
            failed: sourceConfigs === null && !sourceConfigsLoading,
            retry: () => loadSourceConfigs(),
        },
        scouts: {
            choices: scouts,
            loading: scoutConfigs === null && scoutConfigsLoading,
            failed: scoutConfigs === null && !scoutConfigsLoading,
            retry: () => loadScoutConfigs(),
        },
        selection,
        hasSelection: sourceProductFilter.length > 0 || scoutFilter.length > 0,
        label,
        ensureSourceConfigs: () => {
            if (sourceConfigs === null && !sourceConfigsLoading) {
                loadSourceConfigs()
            }
        },
        setSourceFilter,
    }
}
