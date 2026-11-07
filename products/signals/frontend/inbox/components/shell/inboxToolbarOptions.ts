import {
    INBOX_CREATED_WINDOW_OPTIONS,
    INBOX_MODEL_SORT_OPTIONS,
    INBOX_SORT_OPTIONS,
    PRIORITY_MEANING,
    inboxSortOptionKey,
} from '../../filterOptions'
import type { InboxSortOption } from '../../filterOptions'
import type { InboxCreatedWindow, InboxSortDirection, InboxSortField } from '../../logics/inboxFiltersLogic'
import { SignalReportPriority } from '../../types'

// Labels and option lists the Lemon toolbar and the quill filter menu share.

export const INBOX_ANY_TIME_LABEL = 'Any time'

export const INBOX_MODEL_SORT_SECTION_TITLE = 'Model scores'

export const INBOX_SCOPE_FOR_YOU_LABEL = 'For you'
export const INBOX_SCOPE_CLAIMED_BY_YOU_LABEL = 'Claimed by you'
export const INBOX_SCOPE_ENTIRE_PROJECT_LABEL = 'Entire project'
export const INBOX_SCOPE_HELP =
    "See the reports suggested to you, the reports you claimed, every report in the project, or a teammate's"

// Mirrors MODEL_SORT_DEFAULT_WINDOW in inboxFiltersLogic: a ranking sort applies this window on its own,
// so it is that sort's default rather than a filter.
const RANKING_SORT_DEFAULT_WINDOW: InboxCreatedWindow = '7d'

export function inboxPriorityOptionLabel(priority: SignalReportPriority): string {
    return `${priority} · ${PRIORITY_MEANING[priority].label}`
}

export function inboxCreatedWindowLabel(window: InboxCreatedWindow | null): string {
    return INBOX_CREATED_WINDOW_OPTIONS.find((option) => option.value === window)?.label ?? INBOX_ANY_TIME_LABEL
}

export function inboxDefaultCreatedWindow(rankingSort: boolean): InboxCreatedWindow | null {
    return rankingSort ? RANKING_SORT_DEFAULT_WINDOW : null
}

/** Every sort the menu offers. The model sorts are behind their own flag. */
export function inboxOfferedSortOptions(modelSortAvailable: boolean): InboxSortOption[] {
    return modelSortAvailable ? [...INBOX_SORT_OPTIONS, ...INBOX_MODEL_SORT_OPTIONS] : INBOX_SORT_OPTIONS
}

export function inboxSortLabel(
    field: InboxSortField,
    direction: InboxSortDirection,
    modelSortAvailable: boolean
): string {
    return (
        inboxOfferedSortOptions(modelSortAvailable).find(
            (option) => option.field === field && option.direction === direction
        )?.label ?? ''
    )
}

/** The offered sort a select key (`field:direction`) names, or undefined for one the menu does not offer. */
export function inboxSortOptionForKey(key: string, modelSortAvailable: boolean): InboxSortOption | undefined {
    return inboxOfferedSortOptions(modelSortAvailable).find(
        (option) => inboxSortOptionKey(option.field, option.direction) === key
    )
}
