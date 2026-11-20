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

import { userLogic } from 'scenes/userLogic'

import {
    INBOX_CREATED_WINDOW_OPTIONS,
    INBOX_MODEL_SORT_OPTIONS,
    INBOX_PERSONAL_SORT_OPTION,
    INBOX_PRIORITY_OPTIONS,
    INBOX_SORT_OPTIONS,
    inboxSortOptionKey,
} from '../../filterOptions'
import { parseTeammateInboxScope, teammateInboxScope } from '../../inboxMembership'
import { inboxSceneLogic } from '../../inboxSceneLogic'
import { InboxCreatedWindow, InboxSourceSelection, inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { scoutFleetLogic } from '../../logics/scoutFleetLogic'
import { signalSourcesLogic } from '../../signalSourcesLogic'
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
import { buildInboxSourceChoices, singleInboxSourceSelection } from '../../utils/inboxSourceFilter'

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

const ALL_SOURCES = 'all'

function sourceValue(selection: InboxSourceSelection): string {
    return `${selection.kind}:${selection.value}`
}

function sourceSelection(value: string): InboxSourceSelection | null {
    if (value === ALL_SOURCES) {
        return null
    }
    const [kind, ...rest] = value.split(':')
    return { kind: kind as InboxSourceSelection['kind'], value: rest.join(':') }
}

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
        sourceProductFilter,
        scoutFilter,
        availableReviewers,
        knownTeammate,
        activeCreatedWindow,
        timeWindowAvailable,
        sourceFilterAvailable,
        hasActiveFilters,
    } = useValues(inboxFiltersLogic)
    const {
        setScope,
        setSort,
        toggleState,
        setPriorityFilter,
        setSourceFilter,
        setCreatedWindow,
        clearFilters,
        setKnownTeammate,
    } = useActions(inboxFiltersLogic)
    const { user } = useValues(userLogic)
    const { sourceConfigs, sourceConfigsLoading } = useValues(signalSourcesLogic)
    const { loadSourceConfigs } = useActions(signalSourcesLogic)
    const { scoutConfigs, scoutConfigsLoading } = useValues(scoutFleetLogic)
    const { loadScoutConfigs } = useActions(scoutFleetLogic)
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
    const teammateOptions: FilterOption<InboxScope>[] = availableReviewers
        .filter((reviewer) => reviewer.user_uuid !== user?.uuid)
        .map((reviewer) => ({
            value: teammateInboxScope(reviewer.user_uuid),
            label: reviewer.name || reviewer.email,
        }))
    // The loaded teammates are one page. A scoped teammate outside that page still needs a row to show as chosen.
    const scopedTeammate = parseTeammateInboxScope(scope)
    const scopeOptions = [
        ...SCOPE_OPTIONS,
        ...teammateOptions,
        ...(scopedTeammate && !teammateOptions.some((option) => option.value === scope)
            ? [{ value: scope, label: knownTeammate?.uuid === scopedTeammate ? knownTeammate.label : 'A teammate' }]
            : []),
    ]

    const choices = buildInboxSourceChoices({ sourceConfigs, scoutConfigs, sourceProductFilter, scoutFilter })
    const sourceOptions: FilterOption[] = [
        { value: ALL_SOURCES, label: 'All sources' },
        ...choices.sources.map((choice) => ({ value: sourceValue(choice), label: choice.label })),
        ...choices.scouts.map((choice) => ({ value: sourceValue(choice), label: `Scout · ${choice.label}` })),
    ]
    const selection = singleInboxSourceSelection(sourceProductFilter, scoutFilter)
    const selectedSource = selection ? sourceValue(selection) : ALL_SOURCES

    return (
        <DropdownMenu
            onOpenChange={(open: boolean) => {
                // The Source rows come from the configured sources and scouts, which this page may not hold yet.
                if (open && sourceConfigs === null && !sourceConfigsLoading) {
                    loadSourceConfigs()
                }
                if (open && scoutConfigs === null && !scoutConfigsLoading) {
                    loadScoutConfigs()
                }
            }}
        >
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
                    onChange={(next) => {
                        const teammate = teammateOptions.find((option) => option.value === next)
                        const uuid = parseTeammateInboxScope(next)
                        if (teammate && uuid) {
                            setKnownTeammate(uuid, teammate.label)
                        }
                        setScope(next)
                    }}
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
                    <FilterRadioSubMenu
                        label="Source"
                        options={sourceOptions}
                        value={selectedSource}
                        defaultValue={ALL_SOURCES}
                        onChange={(value) => setSourceFilter(sourceSelection(value))}
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
