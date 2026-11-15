import { EMPTY_SELECTION, TodaySessionSelection } from '~/layout/today/todaySessionSelection'
import { TodayWorkItem } from '~/layout/today/todayWorkItems'

import { SpaceFeedSection } from './spaceFeedEntries'

export type SpaceFeedSelectAllState = 'none' | 'some' | 'all'

/** The sessions the feed shows, top to bottom. PR and canvas rows are not sessions, so they are skipped. */
export function spaceFeedSessions(sections: SpaceFeedSection[]): TodayWorkItem[] {
    return sections.flatMap((section) => section.entries.flatMap((entry) => (entry.kind === 'task' ? entry.item : [])))
}

export function selectAllState(selectedIds: string[], orderedIds: string[]): SpaceFeedSelectAllState {
    if (!selectedIds.length) {
        return 'none'
    }
    const selected = new Set(selectedIds)
    return orderedIds.every((id) => selected.has(id)) ? 'all' : 'some'
}

/** A partial selection grows to every session in view; a full one clears. */
export function toggleAllSelection(selectedIds: string[], orderedIds: string[]): TodaySessionSelection {
    return selectAllState(selectedIds, orderedIds) === 'all' ? EMPTY_SELECTION : { ids: orderedIds, anchorId: null }
}
