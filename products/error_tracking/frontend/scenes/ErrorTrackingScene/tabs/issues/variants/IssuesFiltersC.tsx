import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { IconCheck, IconFilter, IconSort, IconTriangleDown, IconTriangleUp } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

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
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ErrorTrackingIssueAssignee, QuickFilterContext } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { AssigneeDropdown } from 'products/error_tracking/frontend/components/Assignee/AssigneeDropdown'
import { assigneeSelectLogic } from 'products/error_tracking/frontend/components/Assignee/assigneeSelectLogic'
import { ErrorFilters } from 'products/error_tracking/frontend/components/IssueFilters'
import {
    TAXONOMIC_FILTER_LOGIC_KEY,
    TAXONOMIC_GROUP_TYPES,
} from 'products/error_tracking/frontend/components/IssueFilters/consts'
import {
    FilterChip,
    InternalUsersChip,
    IssueFilterChips,
    QuickFilterChips,
    UniversalFilterGroup,
} from 'products/error_tracking/frontend/components/IssueFilters/FilterGroup'
import { issueFiltersLogic } from 'products/error_tracking/frontend/components/IssueFilters/issueFiltersLogic'
import { STATUS_OPTIONS, statusOptionLabel } from 'products/error_tracking/frontend/components/IssueFilters/Status'
import {
    ErrorTrackingQueryOrderBy,
    ORDER_BY_OPTIONS,
    issueQueryOptionsLogic,
} from 'products/error_tracking/frontend/components/IssueQueryOptions/issueQueryOptionsLogic'

import { ERROR_TRACKING_SCENE_LOGIC_KEY } from '../../../errorTrackingSceneLogic'
import { ListReloadButton } from '../IssuesList'

const QUICK_FILTER_CONTEXT = QuickFilterContext.ErrorTrackingIssueFilters

const PLACEHOLDER = 'Search issues, or filter by property...'

// No HogQL in this bar — keeps the "+" menu to filters and search
const GROUP_TYPES = TAXONOMIC_GROUP_TYPES.filter((type) => type !== TaxonomicFilterGroupType.HogQLExpression)

// Synthetic group for the "Search issues matching …" action row
const SEARCH_GROUP = {
    type: 'issue-search' as TaxonomicFilterGroupType,
    name: 'Search',
    getName: (item: { name?: string }) => item?.name ?? '',
} as unknown as TaxonomicFilterGroup

/**
 * Filter bar fronting the rebuilt taxonomic filter (`menu/`): one filter
 * button on the left that opens the multi-level dropdown (New filter… /
 * Pinned, plus issue-specific Status, Assignee, and internal-users
 * entries), with the combobox panel behind "New filter…". The bar itself
 * holds no typing field — just filter chips. The combobox list's first row
 * is a "Search issues matching …" action (auto-highlighted, so plain Enter
 * means "search"); a committed search shows as a chip in the bar.
 */
export function IssuesFiltersC(): JSX.Element {
    const { filterGroup } = useValues(issueFiltersLogic)
    const { setFilterGroup } = useActions(issueFiltersLogic)

    return (
        <UniversalFilters
            rootKey={TAXONOMIC_FILTER_LOGIC_KEY}
            group={filterGroup.values[0] as UniversalFiltersGroup}
            taxonomicGroupTypes={TAXONOMIC_GROUP_TYPES}
            onChange={(group) => setFilterGroup({ type: FilterLogicalOperator.And, values: [group] })}
        >
            <OmniBar />
        </UniversalFilters>
    )
}

const Separator = (): JSX.Element => <div className="w-px h-5 bg-border shrink-0 mx-1" />

const OmniBar = (): JSX.Element => {
    const { searchQuery } = useValues(issueFiltersLogic)
    const { setSearchQuery } = useActions(issueFiltersLogic)
    const { addGroupFilter } = useActions(universalFiltersLogic)

    return (
        <TaxonomicFilterHeadless.Root
            className="contents"
            bindRootProps={false}
            taxonomicGroupTypes={GROUP_TYPES}
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
            <OmniBarInner />
        </TaxonomicFilterHeadless.Root>
    )
}

const OmniBarInner = (): JSX.Element => {
    const { searchQuery: panelQuery } = useTaxonomicFilterContext()
    const { searchQuery } = useValues(issueFiltersLogic)
    const { setSearchQuery } = useActions(issueFiltersLogic)

    const trimmed = panelQuery.trim()
    const leadingEntries = useMemo<MenuFilterEntry[]>(() => {
        if (!trimmed) {
            return []
        }
        return [
            {
                item: { name: trimmed } as TaxonomicDefinitionTypes,
                group: SEARCH_GROUP,
                name: trimmed,
                friendlyLabel: `Search issues matching "${trimmed}"`,
            },
        ]
    }, [trimmed])

    return (
        <div className="flex items-center min-h-11 pr-1.5 rounded-lg border bg-[var(--color-bg-fill-input)] shadow-sm">
            <div className="flex items-center gap-0.5 pl-1.5 shrink-0">
                <ListReloadButton />
                <ErrorFilters.DateRange size="small" type="tertiary" />
                <TaxonomicFilterMenu
                    placeholder={PLACEHOLDER}
                    comboboxLeadingEntries={leadingEntries}
                    hideRecent
                    extraMenuItems={({ close }) => <IssueFilterMenuItems close={close} />}
                    trigger={({ open }) => (
                        <LemonButton
                            size="small"
                            type="tertiary"
                            icon={<IconFilter />}
                            active={open}
                            tooltip="Search and filter issues"
                        />
                    )}
                />
            </div>
            <Separator />
            <div className="flex-1 min-w-0 flex items-center flex-wrap gap-1 px-1">
                <IssueFilterChips />
                <InternalUsersChip />
                <QuickFilterChips context={QUICK_FILTER_CONTEXT} logicKey={ERROR_TRACKING_SCENE_LOGIC_KEY} />
                <UniversalFilterGroup taxonomicGroupTypes={TAXONOMIC_GROUP_TYPES} />
                {searchQuery && <FilterChip onClear={() => setSearchQuery('')}>Search: "{searchQuery}"</FilterChip>}
            </div>
            <Separator />
            <div className="flex items-center gap-0.5 shrink-0">
                <SortFieldButton />
                <SortDirectionButton />
            </div>
        </div>
    )
}

const IssueFilterMenuItems = ({ close }: { close: () => void }): JSX.Element => {
    const { status, assignee } = useValues(issueQueryOptionsLogic)
    const { setStatus, setAssignee } = useActions(issueQueryOptionsLogic)
    const { filterTestAccounts } = useValues(issueFiltersLogic)
    const { setFilterTestAccounts } = useActions(issueFiltersLogic)
    const { currentTeam } = useValues(teamLogic)
    const { setLocalDefault } = useActions(filterTestAccountsDefaultsLogic)

    const hasTestAccountFilters = (currentTeam?.test_account_filters || []).length > 0

    return (
        <>
            <DropdownMenuSeparator />
            <DropdownMenuSub>
                <DropdownMenuSubTrigger>Status</DropdownMenuSubTrigger>
                <DropdownMenuSubContent>
                    {STATUS_OPTIONS.map((option) => (
                        <DropdownMenuItem key={option} onClick={() => setStatus(option)}>
                            {statusOptionLabel(option)}
                            {(status ?? 'active') === option && <IconCheck className="ml-auto size-3.5" />}
                        </DropdownMenuItem>
                    ))}
                </DropdownMenuSubContent>
            </DropdownMenuSub>
            <DropdownMenuSub>
                <DropdownMenuSubTrigger>Assignee</DropdownMenuSubTrigger>
                <DropdownMenuSubContent className="p-0">
                    <AssigneeSubmenu
                        assignee={assignee ?? null}
                        onChange={(value) => {
                            setAssignee(value)
                            close()
                        }}
                    />
                </DropdownMenuSubContent>
            </DropdownMenuSub>
            <DropdownMenuCheckboxItem
                checked={hasTestAccountFilters ? filterTestAccounts : false}
                disabled={!hasTestAccountFilters}
                onCheckedChange={(checked: boolean) => {
                    setFilterTestAccounts(checked)
                    setLocalDefault(checked)
                }}
            >
                Filter out internal and test users
            </DropdownMenuCheckboxItem>
        </>
    )
}

const AssigneeSubmenu = ({
    assignee,
    onChange,
}: {
    assignee: ErrorTrackingIssueAssignee | null
    onChange: (assignee: ErrorTrackingIssueAssignee | null) => void
}): JSX.Element => {
    const { ensureAssigneeTypesLoaded, setSearch } = useActions(assigneeSelectLogic)

    useEffect(() => {
        ensureAssigneeTypesLoaded()
    }, [ensureAssigneeTypesLoaded])

    return (
        <AssigneeDropdown
            assignee={assignee}
            onChange={(value) => {
                setSearch('')
                onChange(value)
            }}
        />
    )
}

const SortFieldButton = (): JSX.Element => {
    const { orderBy } = useValues(issueQueryOptionsLogic)
    const { setOrderBy } = useActions(issueQueryOptionsLogic)

    return (
        <LemonMenu
            items={Object.entries(ORDER_BY_OPTIONS).map(([value, label]) => ({
                label,
                active: orderBy === value,
                onClick: () => setOrderBy(value as ErrorTrackingQueryOrderBy),
            }))}
        >
            <LemonButton size="small" type="tertiary" icon={<IconSort />} tooltip="Sort by">
                {ORDER_BY_OPTIONS[orderBy]}
            </LemonButton>
        </LemonMenu>
    )
}

const SortDirectionButton = (): JSX.Element => {
    const { orderDirection } = useValues(issueQueryOptionsLogic)
    const { setOrderDirection } = useActions(issueQueryOptionsLogic)

    return (
        <LemonButton
            size="small"
            type="tertiary"
            icon={orderDirection === 'DESC' ? <IconTriangleDown /> : <IconTriangleUp />}
            onClick={() => setOrderDirection(orderDirection === 'DESC' ? 'ASC' : 'DESC')}
            tooltip={
                orderDirection === 'DESC'
                    ? 'Newest first — click for oldest first'
                    : 'Oldest first — click for newest first'
            }
        />
    )
}
