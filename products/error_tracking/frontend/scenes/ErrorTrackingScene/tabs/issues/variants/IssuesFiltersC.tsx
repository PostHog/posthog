import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { IconFilter, IconSearch, IconSort, IconTriangleDown, IconTriangleUp, IconX } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { TaxonomicFilterHeadless, useTaxonomicFilterContext } from 'lib/components/TaxonomicFilter/headless'
import { MenuFilterCombobox, MenuFilterEntry } from 'lib/components/TaxonomicFilter/menu'
import {
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
} from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
// products/ can't resolve bare @posthog/quill (no vite alias) — go through the barrel
import { Popover, PopoverContent, PopoverTrigger } from 'lib/ui/quill'
import { cn } from 'lib/utils/css-classes'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { ErrorFilters } from 'products/error_tracking/frontend/components/IssueFilters'
import {
    TAXONOMIC_FILTER_LOGIC_KEY,
    TAXONOMIC_GROUP_TYPES,
} from 'products/error_tracking/frontend/components/IssueFilters/consts'
import {
    InternalUsersChip,
    IssueFilterChips,
    QuickFilterChips,
    UniversalFilterGroup,
} from 'products/error_tracking/frontend/components/IssueFilters/FilterGroup'
import { issueFiltersLogic } from 'products/error_tracking/frontend/components/IssueFilters/issueFiltersLogic'
import {
    ErrorTrackingQueryOrderBy,
    ORDER_BY_OPTIONS,
    issueQueryOptionsLogic,
} from 'products/error_tracking/frontend/components/IssueQueryOptions/issueQueryOptionsLogic'

import { ERROR_TRACKING_SCENE_LOGIC_KEY } from '../../../errorTrackingSceneLogic'
import { ListReloadButton } from '../IssuesList'

const QUICK_FILTER_CONTEXT = QuickFilterContext.ErrorTrackingIssueFilters

const PLACEHOLDER = 'Search issues, or filter by property...'

// No HogQL in this variant — it lives behind the rebuild's dropdown menu, which C skips
const GROUP_TYPES = TAXONOMIC_GROUP_TYPES.filter((type) => type !== TaxonomicFilterGroupType.HogQLExpression)

// Synthetic group for the "Search issues matching …" action row
const SEARCH_GROUP = {
    type: 'issue-search' as TaxonomicFilterGroupType,
    name: 'Search',
    getName: (item: { name?: string }) => item?.name ?? '',
} as unknown as TaxonomicFilterGroup

/**
 * Variant C — the rebuild's packaged combobox panel (`menu/`):
 * input + category select + preview pane, hosted in a popover. The bar's
 * search slot is a trigger; the panel owns the typing field. The list's
 * first row is a "Search issues matching …" action (auto-highlighted, so
 * plain Enter still means "search"), with taxonomic matches below it.
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
    const { addGroupFilter } = useActions(universalFiltersLogic)

    return (
        <TaxonomicFilterHeadless.Root
            className="contents"
            bindRootProps={false}
            taxonomicGroupTypes={GROUP_TYPES}
            initialSearchQuery={searchQuery}
            onChange={(group, value, item) => addGroupFilter(group, value, item)}
            excludedProperties={{ [TaxonomicFilterGroupType.ErrorTrackingIssues]: ['assignee'] }}
        >
            <OmniBarInner />
        </TaxonomicFilterHeadless.Root>
    )
}

const OmniBarInner = (): JSX.Element => {
    const [visible, setVisible] = useState<boolean>(false)
    const { searchQuery: panelQuery, setSearchQuery: setPanelQuery, selectItem } = useTaxonomicFilterContext()
    const { searchQuery } = useValues(issueFiltersLogic)
    const { setSearchQuery } = useActions(issueFiltersLogic)

    // Whatever closed the panel (Esc, outside click, a commit), its input
    // falls back to the search that is actually applied to the list.
    useEffect(() => {
        if (!visible) {
            setPanelQuery(searchQuery)
        }
    }, [visible, searchQuery, setPanelQuery])

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent): void => {
            if (event.key !== '/' || event.metaKey || event.ctrlKey || event.altKey) {
                return
            }
            const target = event.target as HTMLElement | null
            if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
                return
            }
            event.preventDefault()
            setVisible(true)
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    }, [])

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

    const onCommit = (entry: MenuFilterEntry): void => {
        if (entry.group.type === SEARCH_GROUP.type) {
            setSearchQuery(entry.name)
        } else {
            const value = entry.group.getValue?.(entry.item) ?? null
            selectItem(entry.group, value, entry.item)
        }
        setVisible(false)
    }

    return (
        <div
            className={cn(
                'flex items-center min-h-11 pr-1.5 rounded-lg border bg-[var(--color-bg-fill-input)] shadow-sm transition-colors',
                visible && 'border-[var(--color-border-bold)]'
            )}
        >
            <div className="flex items-center gap-0.5 pl-1.5 shrink-0">
                <ListReloadButton />
                <ErrorFilters.DateRange size="small" type="tertiary" />
                <ErrorFilters.SettingsMenu
                    icon={<IconFilter />}
                    quickFilterContext={QUICK_FILTER_CONTEXT}
                    logicKey={ERROR_TRACKING_SCENE_LOGIC_KEY}
                />
            </div>
            <Separator />
            <IconSearch className="ml-1 text-lg text-muted shrink-0" />
            <div className="flex-1 min-w-0 flex items-center flex-wrap gap-1 px-1">
                <IssueFilterChips />
                <InternalUsersChip />
                <QuickFilterChips context={QUICK_FILTER_CONTEXT} logicKey={ERROR_TRACKING_SCENE_LOGIC_KEY} />
                <UniversalFilterGroup taxonomicGroupTypes={TAXONOMIC_GROUP_TYPES} />
                <Popover open={visible} onOpenChange={setVisible}>
                    <PopoverTrigger
                        render={
                            <button
                                type="button"
                                className="flex flex-1 min-w-[160px] items-center h-8 px-1 rounded text-left text-sm bg-transparent border-0 cursor-pointer hover:bg-fill-button-tertiary-hover"
                            >
                                {searchQuery ? (
                                    <span className="truncate">{searchQuery}</span>
                                ) : (
                                    <span className="text-muted truncate">{PLACEHOLDER}</span>
                                )}
                            </button>
                        }
                    />
                    <PopoverContent
                        align="start"
                        side="bottom"
                        sideOffset={4}
                        className="p-0 gap-0 overflow-hidden flex flex-col w-[calc(100vw-2rem)] md:w-[720px] h-[400px]"
                    >
                        <MenuFilterCombobox
                            drillTo="all"
                            title="Search issues"
                            placeholder={PLACEHOLDER}
                            leadingEntries={leadingEntries}
                            onCommit={onCommit}
                            onBack={() => setVisible(false)}
                        />
                    </PopoverContent>
                </Popover>
            </div>
            {searchQuery && (
                <LemonButton size="xsmall" icon={<IconX />} tooltip="Clear search" onClick={() => setSearchQuery('')} />
            )}
            {!visible && (
                <kbd className="hidden md:inline-flex items-center justify-center shrink-0 rounded border px-1.5 h-5 mr-1 text-xs text-muted font-mono">
                    /
                </kbd>
            )}
            <Separator />
            <div className="flex items-center gap-0.5 shrink-0">
                <SortFieldButton />
                <SortDirectionButton />
            </div>
        </div>
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
