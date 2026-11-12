import { useActions, useValues } from 'kea'

import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuSeparator,
    FilterCheckboxSubMenu,
    FilterClearItem,
    FilterMenuTrigger,
    FilterOption,
    FilterRadioSubMenu,
} from '@posthog/quill'

import {
    INBOX_CREATED_WINDOW_OPTIONS,
    INBOX_MODEL_SORT_OPTIONS,
    INBOX_PERSONAL_SORT_OPTION,
    INBOX_PRIORITY_OPTIONS,
    INBOX_SORT_OPTIONS,
    INBOX_SOURCE_OPTIONS,
    inboxSortOptionKey,
} from '../../filterOptions'
import { inboxSceneLogic } from '../../inboxSceneLogic'
import { InboxCreatedWindow, inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import {
    INBOX_REPORT_SECTION_LABEL,
    INBOX_SCOPE_CLAIMED_BY_YOU,
    INBOX_SCOPE_ENTIRE_PROJECT,
    INBOX_SCOPE_FOR_YOU,
    InboxReportSectionKey,
    InboxScope,
    SignalReportPriority,
} from '../../types'
import { selectedFlatListSections } from '../../utils/flatReportList'

const ANY_TIME = 'any'

const SCOPE_OPTIONS: FilterOption<InboxScope>[] = [
    { value: INBOX_SCOPE_ENTIRE_PROJECT, label: 'All reports' },
    { value: INBOX_SCOPE_FOR_YOU, label: 'For you' },
    { value: INBOX_SCOPE_CLAIMED_BY_YOU, label: 'Claimed by you' },
]

const TIME_OPTIONS: FilterOption<InboxCreatedWindow | typeof ANY_TIME>[] = [
    { value: ANY_TIME, label: 'Any time' },
    ...INBOX_CREATED_WINDOW_OPTIONS.map(({ value, label }) => ({ value, label })),
]

const PRIORITY_OPTIONS: FilterOption<SignalReportPriority>[] = INBOX_PRIORITY_OPTIONS.map((priority) => ({
    value: priority,
    label: priority,
}))

const SOURCE_OPTIONS: FilterOption[] = INBOX_SOURCE_OPTIONS.map(({ value, label, icon }) => ({ value, label, icon }))

function changed<Value>(before: readonly Value[], after: readonly Value[]): Value[] {
    return [...before.filter((value) => !after.includes(value)), ...after.filter((value) => !before.includes(value))]
}

/** Every control that shapes the report list, in one menu: sort and scope, then the filters, then Clear filters. */
export function QuillInboxFilterMenu(): JSX.Element {
    const {
        scope,
        activeSortField,
        activeSortDirection,
        modelSortAvailable,
        personalSortAvailable,
        visibleStateFilter,
        priorityFilter,
        activeSourceProductFilter,
        activeCreatedWindow,
        timeWindowAvailable,
        sourceFilterAvailable,
        hasActiveFilters,
    } = useValues(inboxFiltersLogic)
    const { setScope, setSort, toggleState, setPriorityFilter, toggleSourceProduct, setCreatedWindow, clearFilters } =
        useActions(inboxFiltersLogic)
    const { isStaff } = useValues(inboxSceneLogic)

    const sortOptions = [
        ...INBOX_SORT_OPTIONS,
        ...(personalSortAvailable ? [INBOX_PERSONAL_SORT_OPTION] : []),
        ...(modelSortAvailable ? INBOX_MODEL_SORT_OPTIONS : []),
    ]
    const stateOptions: FilterOption<InboxReportSectionKey>[] = selectedFlatListSections([], isStaff).map((key) => ({
        value: key,
        label: INBOX_REPORT_SECTION_LABEL[key],
    }))
    // A teammate scope comes from a shared link, so it shows as a row only while it is in force.
    const scopeOptions = SCOPE_OPTIONS.some((option) => option.value === scope)
        ? SCOPE_OPTIONS
        : [...SCOPE_OPTIONS, { value: scope, label: 'A teammate' }]

    return (
        <DropdownMenu>
            <FilterMenuTrigger active={hasActiveFilters} dataAttr="inbox-filter-menu" />
            <DropdownMenuContent align="end" className="min-w-64">
                <FilterRadioSubMenu
                    label="Sort"
                    options={sortOptions.map((option) => ({
                        value: inboxSortOptionKey(option.field, option.direction),
                        label: option.label,
                    }))}
                    value={inboxSortOptionKey(activeSortField, activeSortDirection)}
                    onChange={(key) => {
                        const option = sortOptions.find((o) => inboxSortOptionKey(o.field, o.direction) === key)
                        if (option) {
                            setSort(option.field, option.direction)
                        }
                    }}
                    dataAttr="inbox-sort"
                />
                <FilterRadioSubMenu
                    label="Scope"
                    options={scopeOptions}
                    value={scope}
                    onChange={setScope}
                    dataAttr="inbox-scope"
                />
                <DropdownMenuSeparator />
                <FilterCheckboxSubMenu
                    label="Status"
                    allLabel="All statuses"
                    pluralNoun="statuses"
                    options={stateOptions}
                    selected={visibleStateFilter}
                    onChange={(next) => changed(visibleStateFilter, next).forEach((state) => toggleState(state))}
                    dataAttr="inbox-state-filter"
                />
                <FilterCheckboxSubMenu
                    label="Priority"
                    allLabel="All priorities"
                    pluralNoun="priorities"
                    options={PRIORITY_OPTIONS}
                    selected={priorityFilter}
                    onChange={setPriorityFilter}
                    dataAttr="inbox-priority-filter"
                    optionDataAttr="inbox-priority-filter-option"
                />
                {timeWindowAvailable && (
                    <FilterRadioSubMenu
                        label="Time"
                        options={TIME_OPTIONS}
                        value={activeCreatedWindow ?? ANY_TIME}
                        defaultValue={ANY_TIME}
                        onChange={(value) => setCreatedWindow(value === ANY_TIME ? null : value)}
                        dataAttr="inbox-created-filter"
                    />
                )}
                {sourceFilterAvailable && (
                    <FilterCheckboxSubMenu
                        label="Source"
                        allLabel="All sources"
                        pluralNoun="sources"
                        options={SOURCE_OPTIONS}
                        selected={activeSourceProductFilter}
                        onChange={(next) =>
                            changed(activeSourceProductFilter, next).forEach((source) => toggleSourceProduct(source))
                        }
                        dataAttr="inbox-source-filter"
                    />
                )}
                <FilterClearItem
                    active={hasActiveFilters}
                    onClear={() => clearFilters()}
                    dataAttr="inbox-filter-clear"
                />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
