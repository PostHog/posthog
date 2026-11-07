import { useActions, useValues } from 'kea'

import {
    Badge,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    FilterClearItem,
    FilterMenuTrigger,
    FilterSubMenu,
} from '@posthog/quill'

import {
    INBOX_CREATED_WINDOW_OPTIONS,
    INBOX_MODEL_SORT_OPTIONS,
    INBOX_PRIORITY_OPTIONS,
    INBOX_SORT_OPTIONS,
    InboxSortOption,
    inboxPriorityFilterLabel,
    inboxSortOptionKey,
    isRankingSortField,
} from '../../filterOptions'
import { InboxCreatedWindow, inboxFiltersLogic, isDefaultStateFilter } from '../../logics/inboxFiltersLogic'
import {
    INBOX_REPORT_SECTION_DESCRIPTION,
    INBOX_REPORT_SECTION_LABEL,
    INBOX_REPORT_SECTION_TAG,
    SignalReportPriority,
} from '../../types'
import { InboxPriorityDot } from './InboxPriorityDot'
import {
    INBOX_ANY_TIME_LABEL,
    INBOX_MODEL_SORT_SECTION_TITLE,
    inboxCreatedWindowLabel,
    inboxDefaultCreatedWindow,
    inboxPriorityOptionLabel,
    inboxSortLabel,
    inboxSortOptionForKey,
} from './inboxToolbarOptions'
import { QuillInboxScopeSubMenu } from './QuillInboxScopeSubMenu'
import { QuillInboxSourceSubMenu } from './QuillInboxSourceSubMenu'
import { useInboxStateFilterOptions } from './useInboxStateFilterOptions'

// Radio values are strings, so "no priority" and "any time" need a value of their own.
const ALL_PRIORITIES = 'all'
const ANY_TIME = 'any'

function SortRadioItem({ option }: { option: InboxSortOption }): JSX.Element {
    return (
        <DropdownMenuRadioItem value={inboxSortOptionKey(option.field, option.direction)} tooltip={option.description}>
            {option.label}
        </DropdownMenuRadioItem>
    )
}

/**
 * The quill sibling of the Reports toolbar (`InboxReportFilters`, `InboxFiltersPanel`, `InboxSortSelect` and
 * `InboxScopeFilter`): one funnel menu. Scope and sort come first and never count as filters. Then status,
 * priority, the created-in window and source, each behind its own flag where the Lemon toolbar gates it.
 */
export function QuillInboxReportFilters(): JSX.Element {
    const {
        activeSortField,
        activeSortDirection,
        modelSortAvailable,
        stateFilter,
        visibleStateFilter,
        priorityFilter,
        createdWindow,
        timeWindowAvailable,
        sourceFilterAvailable,
        nonDefaultReportFilterCount,
    } = useValues(inboxFiltersLogic)
    const { setSort, toggleState, setPriorityFilter, setCreatedWindow, clearFilters } = useActions(inboxFiltersLogic)
    const { options: stateOptions, label: stateLabel } = useInboxStateFilterOptions()

    const filtersOn = nonDefaultReportFilterCount > 0
    const createdWindowOn =
        createdWindow !== null && createdWindow !== inboxDefaultCreatedWindow(isRankingSortField(activeSortField))
    const priorityValue =
        priorityFilter.length === 0 ? ALL_PRIORITIES : priorityFilter.length === 1 ? priorityFilter[0] : null

    return (
        <DropdownMenu>
            {/* pinned: autocapture selector shared with the Lemon compact filters button. */}
            <FilterMenuTrigger active={filtersOn} dataAttr="inbox-filters-panel" />
            <DropdownMenuContent align="start" className="min-w-64">
                <QuillInboxScopeSubMenu />
                <FilterSubMenu
                    label="Sort by"
                    value={inboxSortLabel(activeSortField, activeSortDirection, modelSortAvailable)}
                    dataAttr="inbox-sort"
                >
                    <DropdownMenuRadioGroup
                        value={inboxSortOptionKey(activeSortField, activeSortDirection)}
                        onValueChange={(key) => {
                            const option = inboxSortOptionForKey(String(key), modelSortAvailable)
                            if (option) {
                                setSort(option.field, option.direction)
                            }
                        }}
                    >
                        {INBOX_SORT_OPTIONS.map((option) => (
                            <SortRadioItem key={inboxSortOptionKey(option.field, option.direction)} option={option} />
                        ))}
                        {modelSortAvailable && (
                            <>
                                <DropdownMenuSeparator />
                                <DropdownMenuGroup>
                                    <DropdownMenuLabel>{INBOX_MODEL_SORT_SECTION_TITLE}</DropdownMenuLabel>
                                    {INBOX_MODEL_SORT_OPTIONS.map((option) => (
                                        <SortRadioItem
                                            key={inboxSortOptionKey(option.field, option.direction)}
                                            option={option}
                                        />
                                    ))}
                                </DropdownMenuGroup>
                            </>
                        )}
                    </DropdownMenuRadioGroup>
                </FilterSubMenu>
                <DropdownMenuSeparator />
                <FilterSubMenu
                    label="Status"
                    value={stateLabel}
                    active={!isDefaultStateFilter(visibleStateFilter)}
                    dataAttr="inbox-filter-state"
                >
                    {stateOptions.map((key) => {
                        const tag = INBOX_REPORT_SECTION_TAG[key]
                        return (
                            <DropdownMenuCheckboxItem
                                key={key}
                                checked={stateFilter.includes(key)}
                                closeOnClick={false}
                                onCheckedChange={() => toggleState(key)}
                                tooltip={INBOX_REPORT_SECTION_DESCRIPTION[key]}
                                data-attr={`inbox-filter-state-${key}`}
                            >
                                {INBOX_REPORT_SECTION_LABEL[key]}
                                {tag && <Badge className="ml-auto">{tag}</Badge>}
                            </DropdownMenuCheckboxItem>
                        )
                    })}
                </FilterSubMenu>
                <FilterSubMenu
                    label="Priority"
                    // A shared link can carry several priorities, which no single option represents, so the
                    // row reads the selection out of the filter itself.
                    value={inboxPriorityFilterLabel(priorityFilter)}
                    active={priorityFilter.length > 0}
                    dataAttr="inbox-filter-priority"
                >
                    <DropdownMenuRadioGroup
                        value={priorityValue}
                        onValueChange={(next) =>
                            setPriorityFilter(next === ALL_PRIORITIES ? [] : [next as SignalReportPriority])
                        }
                    >
                        <DropdownMenuRadioItem value={ALL_PRIORITIES}>
                            {inboxPriorityFilterLabel([])}
                        </DropdownMenuRadioItem>
                        {INBOX_PRIORITY_OPTIONS.map((priority) => (
                            <DropdownMenuRadioItem key={priority} value={priority}>
                                <InboxPriorityDot priority={priority} />
                                {inboxPriorityOptionLabel(priority)}
                            </DropdownMenuRadioItem>
                        ))}
                    </DropdownMenuRadioGroup>
                </FilterSubMenu>
                {timeWindowAvailable && (
                    <FilterSubMenu
                        label="Created"
                        value={inboxCreatedWindowLabel(createdWindow)}
                        active={createdWindowOn}
                        dataAttr="inbox-filter-created-window"
                    >
                        <DropdownMenuRadioGroup
                            value={createdWindow ?? ANY_TIME}
                            onValueChange={(next) =>
                                setCreatedWindow(next === ANY_TIME ? null : (next as InboxCreatedWindow))
                            }
                        >
                            <DropdownMenuRadioItem value={ANY_TIME}>{INBOX_ANY_TIME_LABEL}</DropdownMenuRadioItem>
                            {INBOX_CREATED_WINDOW_OPTIONS.map(({ value, label }) => (
                                <DropdownMenuRadioItem key={value} value={value}>
                                    {label}
                                </DropdownMenuRadioItem>
                            ))}
                        </DropdownMenuRadioGroup>
                    </FilterSubMenu>
                )}
                {sourceFilterAvailable && <QuillInboxSourceSubMenu />}
                <FilterClearItem active={filtersOn} onClear={clearFilters} dataAttr="inbox-filters-reset" />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
