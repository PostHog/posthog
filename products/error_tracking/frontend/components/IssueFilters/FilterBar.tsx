import { useActions, useValues } from 'kea'
import { ReactNode, useMemo } from 'react'

import { IconCheck, IconFilter } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import {
    QuickFiltersModal,
    quickFiltersLogic,
    quickFiltersModalLogic,
    quickFiltersSectionLogic,
} from 'lib/components/QuickFilters'
import { TaxonomicFilterHeadless, useTaxonomicFilterContext } from 'lib/components/TaxonomicFilter/headless'
import { MenuFilterEntry, TaxonomicFilterMenu } from 'lib/components/TaxonomicFilter/menu'
import {
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
} from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
// products/ can't resolve bare @posthog/quill (no vite alias) — go through the barrel
import {
    DropdownMenuCheckboxItem,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
} from 'lib/ui/quill'
import { cn } from 'lib/utils/css-classes'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, PropertyFilterType, QuickFilter, UniversalFiltersGroup } from '~/types'

import { issueQueryOptionsLogic } from '../IssueQueryOptions/issueQueryOptionsLogic'
import { TAXONOMIC_FILTER_LOGIC_KEY, TAXONOMIC_GROUP_TYPES } from './consts'
import { DateRangeFilter } from './DateRange'
import {
    AssigneeEditor,
    excludeFilterTypesFromGroup,
    FilterChip,
    InternalUsersChip,
    IssueFilterChips,
    QuickFilterChips,
    UniversalFilterGroup,
} from './FilterGroup'
import { issueFiltersLogic } from './issueFiltersLogic'
import { SortControl } from './SortControl'
import { STATUS_OPTIONS, statusOptionLabelWithDescription } from './Status'

// Synthetic group for the "Search … matching …" action row. No getValue on
// purpose — a null value keeps search commits out of taxonomic recents.
const SEARCH_GROUP = {
    type: 'issue-search' as TaxonomicFilterGroupType,
    name: 'Search',
    getName: (item: { name?: string }) => item?.name ?? '',
} as unknown as TaxonomicFilterGroup

export interface FilterBarProps {
    /** Surface-provided reload button, leading the bar. */
    reload?: ReactNode
    /** Scopes quick filter selections and quick filter chips. */
    logicKey?: string
    /** Enables the quick filter menu entries, chips, and setup modal. */
    quickFilterContext?: QuickFilterContext
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    /** Filter types hidden from the chips, for surfaces whose queries ignore them. */
    excludeFilterTypes?: PropertyFilterType[]
    /** Status / assignee / sort controls — requires a bound issueQueryOptionsLogic. */
    showIssueControls?: boolean
    /** Free-text search action in the popover. Disable on surfaces that ignore searchQuery. */
    showSearch?: boolean
    /** What free-text search applies to — drives the placeholder and search action label. */
    searchSubject?: string
    /**
     * Presentation: `bar` is the default filled/bordered pill. `inline` deconstructs it into
     * zones (date + reload left, filter button + pills floating in the middle with no background,
     * sort right) for a lighter, Linear-style toolbar.
     */
    variant?: 'bar' | 'inline'
    className?: string
}

/**
 * The error tracking filter bar, fronting the rebuilt taxonomic filter
 * (`TaxonomicFilter/menu`): one filter button on the left that opens the
 * multi-level dropdown (New filter… / Pinned, plus status, assignee, quick
 * filters, and internal-users entries), with the combobox panel behind
 * "New filter…". The bar itself holds no typing field — just filter chips.
 * The combobox list's first row is a "Search … matching …" action
 * (auto-highlighted, so plain Enter means "search"); a committed search
 * shows as a chip in the bar.
 */
export function FilterBar({
    reload,
    logicKey,
    quickFilterContext,
    taxonomicGroupTypes = TAXONOMIC_GROUP_TYPES,
    excludeFilterTypes,
    showIssueControls = true,
    showSearch = true,
    searchSubject = 'issues',
    variant = 'bar',
    className,
}: FilterBarProps): JSX.Element {
    const { filterGroup } = useValues(issueFiltersLogic)
    const { setFilterGroup } = useActions(issueFiltersLogic)

    const displayGroup = excludeFilterTypesFromGroup(filterGroup.values[0] as UniversalFiltersGroup, excludeFilterTypes)

    return (
        <UniversalFilters
            rootKey={TAXONOMIC_FILTER_LOGIC_KEY}
            group={displayGroup}
            taxonomicGroupTypes={taxonomicGroupTypes}
            onChange={(group) => setFilterGroup({ type: FilterLogicalOperator.And, values: [group] })}
        >
            <Bar
                reload={reload}
                logicKey={logicKey}
                quickFilterContext={quickFilterContext}
                taxonomicGroupTypes={taxonomicGroupTypes}
                showIssueControls={showIssueControls}
                showSearch={showSearch}
                searchSubject={searchSubject}
                variant={variant}
                className={className}
            />
        </UniversalFilters>
    )
}

type BarProps = Required<
    Pick<FilterBarProps, 'taxonomicGroupTypes' | 'showIssueControls' | 'showSearch' | 'searchSubject' | 'variant'>
> &
    Pick<FilterBarProps, 'reload' | 'logicKey' | 'quickFilterContext' | 'className'>

const Bar = (props: BarProps): JSX.Element => {
    const { searchQuery } = useValues(issueFiltersLogic)
    const { setSearchQuery } = useActions(issueFiltersLogic)
    const { addGroupFilter } = useActions(universalFiltersLogic)

    // No HogQL in the menu — chip editing keeps the full group list
    const menuGroupTypes = useMemo(
        () => props.taxonomicGroupTypes.filter((type) => type !== TaxonomicFilterGroupType.HogQLExpression),
        [props.taxonomicGroupTypes]
    )

    return (
        <TaxonomicFilterHeadless.Root
            className="contents"
            bindRootProps={false}
            taxonomicGroupTypes={menuGroupTypes}
            initialSearchQuery={searchQuery}
            onChange={(group, value, item) => {
                if (group.type === SEARCH_GROUP.type) {
                    setSearchQuery(String((item as { name?: string })?.name ?? ''))
                } else {
                    addGroupFilter(group, value, item)
                }
            }}
            excludedProperties={{ [TaxonomicFilterGroupType.ErrorTrackingIssues]: ['assignee'] }}
        >
            <BarContents {...props} />
        </TaxonomicFilterHeadless.Root>
    )
}

const Separator = (): JSX.Element => <div className="w-px h-5 bg-border shrink-0 mx-1" />

// Filled, bordered button-group surface for the inline variant's side clusters (date/reload, sort).
// No inner padding + squared child buttons means each button fills its segment edge-to-edge (clean
// hover), while overflow-hidden clips the group's outer corners to the rounded container.
const INLINE_CLUSTER =
    'overflow-hidden rounded-lg border bg-[var(--color-bg-fill-input)] shadow-sm [&_.LemonButton]:!rounded-none'

// Full-height divider between buttons in an inline group.
const GroupDivider = (): JSX.Element => <div className="w-px self-stretch bg-border" />

const BarContents = ({
    reload,
    logicKey,
    quickFilterContext,
    taxonomicGroupTypes,
    showIssueControls,
    showSearch,
    searchSubject,
    variant,
    className,
}: BarProps): JSX.Element => {
    const { searchQuery: panelQuery } = useTaxonomicFilterContext()
    const { searchQuery } = useValues(issueFiltersLogic)
    const { setSearchQuery } = useActions(issueFiltersLogic)

    const isInline = variant === 'inline'

    const trimmed = panelQuery.trim()
    const searchEntries = useMemo<MenuFilterEntry[]>(() => {
        if (!showSearch || !trimmed) {
            return []
        }
        return [
            {
                item: {
                    name: trimmed,
                    // Surfaced in the preview pane (via useTaxonomicAutocompleteItemDetails → item.description).
                    description: `Show only ${searchSubject} whose exception type, message, stack trace, or function contains what you've typed.`,
                } as TaxonomicDefinitionTypes,
                group: SEARCH_GROUP,
                name: trimmed,
                friendlyLabel: `Search ${searchSubject} matching "${trimmed}"`,
            },
        ]
    }, [showSearch, trimmed, searchSubject])

    return (
        <div
            className={cn(
                isInline
                    ? 'flex items-center gap-2'
                    : 'flex items-center min-h-11 pr-1.5 rounded-lg border bg-[var(--color-bg-fill-input)] shadow-sm',
                className
            )}
        >
            <div className={cn('flex items-center shrink-0', isInline ? INLINE_CLUSTER : 'gap-0.5 pl-1.5')}>
                {reload}
                {isInline && <GroupDivider />}
                <DateRangeFilter size="small" type="tertiary" />
            </div>
            {/* Inline variant: sort lives as its own island between the date group and the filters. */}
            {isInline && showIssueControls && (
                <div className={cn('flex items-center shrink-0', INLINE_CLUSTER)}>
                    <SortControl />
                </div>
            )}
            {!isInline && <Separator />}
            <div className={cn('flex-1 min-w-0 flex items-center flex-wrap gap-1', !isInline && 'px-1')}>
                {/* Filter trigger as its own island, sized like the date/sort groups. The mr evens the
                    gap to the first chip with the gap between islands (4px chip gap + 4px = 8px). */}
                <div className={cn('flex items-center shrink-0', isInline && [INLINE_CLUSTER, 'mr-1'])}>
                    <TaxonomicFilterMenu
                        typeToSearch
                        placeholder={
                            showSearch ? `Search ${searchSubject}, or filter by property...` : 'Filter by property...'
                        }
                        comboboxLeadingEntries={searchEntries}
                        extraMenuItems={({ close }) => (
                            <>
                                {showIssueControls && (
                                    <>
                                        <DropdownMenuSeparator />
                                        <IssueControlMenuItems close={close} />
                                    </>
                                )}
                                {quickFilterContext && (
                                    <>
                                        <DropdownMenuSeparator />
                                        <QuickFilterMenuItems context={quickFilterContext} logicKey={logicKey} />
                                    </>
                                )}
                                <DropdownMenuSeparator />
                                <InternalUsersMenuItem />
                            </>
                        )}
                        trigger={({ open }) => (
                            <LemonButton
                                size="small"
                                type="tertiary"
                                icon={<IconFilter />}
                                active={open}
                                tooltip={showSearch ? `Search and filter ${searchSubject}` : 'Filter by property'}
                            >
                                {isInline ? 'Filter' : undefined}
                            </LemonButton>
                        )}
                    />
                </div>
                {showIssueControls && <IssueFilterChips />}
                <InternalUsersChip />
                {quickFilterContext && <QuickFilterChips context={quickFilterContext} logicKey={logicKey} />}
                <UniversalFilterGroup taxonomicGroupTypes={taxonomicGroupTypes} showConnector />
                {showSearch && searchQuery && (
                    <FilterChip onClear={() => setSearchQuery('')}>Search: "{searchQuery}"</FilterChip>
                )}
            </div>
            {!isInline && showIssueControls && (
                <>
                    <Separator />
                    <div className="flex items-center gap-0.5 shrink-0">
                        <SortControl />
                    </div>
                </>
            )}
            {quickFilterContext && <QuickFiltersModal context={quickFilterContext} />}
        </div>
    )
}

const IssueControlMenuItems = ({ close }: { close: () => void }): JSX.Element => {
    const { status, assignee } = useValues(issueQueryOptionsLogic)
    const { setStatus, setAssignee } = useActions(issueQueryOptionsLogic)

    return (
        <>
            <DropdownMenuSub>
                <DropdownMenuSubTrigger>Status</DropdownMenuSubTrigger>
                <DropdownMenuSubContent>
                    {STATUS_OPTIONS.map((option) => (
                        <DropdownMenuItem key={option} onClick={() => setStatus(option)} className="!h-auto">
                            {statusOptionLabelWithDescription(option)}
                            {(status ?? 'active') === option && (
                                <IconCheck className="ml-auto size-3.5 self-start mt-2 shrink-0" />
                            )}
                        </DropdownMenuItem>
                    ))}
                </DropdownMenuSubContent>
            </DropdownMenuSub>
            <DropdownMenuSub>
                <DropdownMenuSubTrigger>Assignee</DropdownMenuSubTrigger>
                <DropdownMenuSubContent className="p-0">
                    <AssigneeEditor
                        assignee={assignee ?? null}
                        onChange={(value) => {
                            setAssignee(value)
                            close()
                        }}
                    />
                </DropdownMenuSubContent>
            </DropdownMenuSub>
        </>
    )
}

const QuickFilterMenuItems = ({
    context,
    logicKey,
}: {
    context: QuickFilterContext
    logicKey?: string
}): JSX.Element => {
    const { quickFilters } = useValues(quickFiltersLogic({ context }))
    const { selectedQuickFilters } = useValues(quickFiltersSectionLogic({ context, logicKey }))
    const { setQuickFilterValue, clearQuickFilter } = useActions(quickFiltersSectionLogic({ context, logicKey }))
    const { openModal } = useActions(quickFiltersModalLogic({ context }))

    return (
        <>
            {quickFilters.map((filter: QuickFilter) => {
                const selectedOptionId = selectedQuickFilters[filter.id]?.optionId || null

                if (filter.options.length === 1) {
                    const option = filter.options[0]
                    return (
                        <DropdownMenuCheckboxItem
                            key={filter.id}
                            checked={selectedOptionId === option.id}
                            onCheckedChange={(checked: boolean) =>
                                checked
                                    ? setQuickFilterValue(filter.id, filter.property_name, option)
                                    : clearQuickFilter(filter.id)
                            }
                        >
                            {filter.name}
                        </DropdownMenuCheckboxItem>
                    )
                }

                return (
                    <DropdownMenuSub key={filter.id}>
                        <DropdownMenuSubTrigger>{filter.name}</DropdownMenuSubTrigger>
                        <DropdownMenuSubContent>
                            {filter.options.map((option) => (
                                <DropdownMenuItem
                                    key={option.id}
                                    onClick={() => setQuickFilterValue(filter.id, filter.property_name, option)}
                                >
                                    {option.label}
                                    {selectedOptionId === option.id && <IconCheck className="ml-auto size-3.5" />}
                                </DropdownMenuItem>
                            ))}
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>
                )
            })}
            <DropdownMenuItem onClick={openModal}>
                {quickFilters.length > 0 ? 'Edit quick filters' : 'Set up quick filters'}
            </DropdownMenuItem>
        </>
    )
}

const InternalUsersMenuItem = (): JSX.Element => {
    const { filterTestAccounts } = useValues(issueFiltersLogic)
    const { setFilterTestAccounts } = useActions(issueFiltersLogic)
    const { currentTeam } = useValues(teamLogic)
    const { setLocalDefault } = useActions(filterTestAccountsDefaultsLogic)

    const hasTestAccountFilters = (currentTeam?.test_account_filters || []).length > 0

    if (!hasTestAccountFilters) {
        return (
            <DropdownMenuItem
                onClick={() =>
                    window.open(urls.settings('project-product-analytics', 'internal-user-filtering'), '_blank')
                }
            >
                Set up internal user filtering
            </DropdownMenuItem>
        )
    }

    return (
        <DropdownMenuCheckboxItem
            checked={filterTestAccounts}
            onCheckedChange={(checked: boolean) => {
                setFilterTestAccounts(checked)
                setLocalDefault(checked)
            }}
        >
            Filter out internal and test users
        </DropdownMenuCheckboxItem>
    )
}
