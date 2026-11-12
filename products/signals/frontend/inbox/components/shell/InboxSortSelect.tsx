import { useActions, useValues } from 'kea'

import { IconSort } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'

import {
    INBOX_MODEL_SORT_OPTIONS,
    INBOX_PERSONAL_SORT_OPTION,
    INBOX_SORT_OPTIONS,
    inboxSortOptionKey,
    InboxSortOption,
} from '../../filterOptions'
import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'

// No per-option icons: the trigger always shows the sort icon, and a second icon would crowd the
// label the order is already stated in.
const toSortSelectOption = (option: InboxSortOption): { value: string; label: string; tooltip?: string } => ({
    value: inboxSortOptionKey(option.field, option.direction),
    label: option.label,
    tooltip: option.description,
})
const SORT_SELECT_OPTIONS = INBOX_SORT_OPTIONS.map(toSortSelectOption)

/**
 * The report list's sort order. It orders the list rather than narrowing it, so it sits after the
 * filters. In a very narrow container the trigger shows only the icon, and the tooltip names the order.
 */
export function InboxSortSelect(): JSX.Element {
    const { activeSortField, activeSortDirection, modelSortAvailable, personalSortAvailable } =
        useValues(inboxFiltersLogic)
    const { setSort } = useActions(inboxFiltersLogic)
    const modelSortOptions = [
        ...(personalSortAvailable ? [INBOX_PERSONAL_SORT_OPTION] : []),
        ...(modelSortAvailable ? INBOX_MODEL_SORT_OPTIONS : []),
    ]
    const sortOptions = [...INBOX_SORT_OPTIONS, ...modelSortOptions]
    const activeKey = inboxSortOptionKey(activeSortField, activeSortDirection)
    const activeLabel = sortOptions.find((o) => inboxSortOptionKey(o.field, o.direction) === activeKey)?.label ?? ''

    return (
        <LemonSelect
            size="small"
            value={activeKey}
            onChange={(key) => {
                const option = sortOptions.find((o) => inboxSortOptionKey(o.field, o.direction) === key)
                if (option) {
                    setSort(option.field, option.direction)
                }
            }}
            options={
                modelSortOptions.length > 0
                    ? [
                          { options: SORT_SELECT_OPTIONS },
                          {
                              title: personalSortAvailable ? 'Model' : 'Model scores',
                              options: modelSortOptions.map(toSortSelectOption),
                          },
                      ]
                    : SORT_SELECT_OPTIONS
            }
            icon={<IconSort />}
            tooltip={`Sort: ${activeLabel}`}
            renderButtonContent={(leaf) => <span className="hidden @md:inline">{leaf?.label ?? ''}</span>}
            data-attr="inbox-sort"
        />
    )
}
