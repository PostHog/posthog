import { useActions, useValues } from 'kea'

import { captureInboxReportTagClicked } from '../../inboxAnalytics'
import { INBOX_TAG_FILTER_MAX, inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { SignalReport } from '../../types'

export interface ReportTagToggle {
    /** The report's tags, the ones in the Tags filter first, so the tag a report matched on leads. */
    orderedTags: string[]
    selectedCount: number
    isSelected: (tag: string) => boolean
    /** An unselected tag can't be added once the filter holds its maximum. */
    isDisabled: (tag: string) => boolean
    title: (tag: string) => string
    toggle: (tag: string) => void
}

/** Toggling a report's tags in and out of the inbox Tags filter, for the tag chips on inbox cards. */
export function useReportTagToggle(report: SignalReport): ReportTagToggle {
    const { tagFilter } = useValues(inboxFiltersLogic)
    const { toggleTag } = useActions(inboxFiltersLogic)
    const tags = report.tags ?? []
    const isSelected = (tag: string): boolean => tagFilter.includes(tag)
    const filterFull = tagFilter.length >= INBOX_TAG_FILTER_MAX
    const isDisabled = (tag: string): boolean => !isSelected(tag) && filterFull

    return {
        orderedTags: [...tags.filter(isSelected), ...tags.filter((tag) => !isSelected(tag))],
        selectedCount: tags.filter(isSelected).length,
        isSelected,
        isDisabled,
        title: (tag) =>
            isDisabled(tag)
                ? `You can filter by up to ${INBOX_TAG_FILTER_MAX} tags`
                : isSelected(tag)
                  ? `Stop filtering by ${tag}`
                  : `Show only reports tagged ${tag}`,
        toggle: (tag) => {
            const added = !isSelected(tag)
            toggleTag(tag)
            captureInboxReportTagClicked({
                report,
                surface: 'card',
                added,
                tagFilterCount: tagFilter.length + (added ? 1 : -1),
            })
        },
    }
}
