import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconFilter, IconHourglass, IconPlug, IconSparkles, IconX } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuEmpty,
    DropdownMenuFilterProvider,
    DropdownMenuInput,
    DropdownMenuItem,
    DropdownMenuList,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from '@posthog/quill-primitives'

import { cn } from 'lib/utils/css-classes'

import { DEFAULT_FACET_FILTERS, type McpFacetFilters, mcpAnalyticsFiltersLogic } from '../mcpAnalyticsFiltersLogic'
import { type McpFacets, mcpFacetsLogic } from '../mcpFacetsLogic'
import { MCP_FILTER_ACTIVE_CLASS, McpFacetSelect } from './McpFacetSelect'
import type { McpFacetControl } from './McpSharedFilters'

/** A multi-select in the menu. */
export interface McpQuickFilterList {
    key: string
    /** Singular, sentence case: "Tool", "Outcome". */
    label: string
    /** Plural for the search box, such as "harnesses". */
    searchLabel: string
    options: string[]
    value: string[]
    onChange: (value: string[]) => void
    dataAttr: string
}

/** An on/off filter in the menu. */
export interface McpQuickFilterToggle {
    key: string
    label: string
    icon: ReactNode
    tooltip: string
    value: boolean
    onChange: (value: boolean) => void
    /** Set when the filter can't apply, and says why. */
    disabledReason?: string
    dataAttr: string
}

/** Filters only one tab has, listed after the shared ones. */
export interface McpPageQuickFilters {
    lists?: McpQuickFilterList[]
    toggles?: McpQuickFilterToggle[]
}

type FacetListKey = 'tools' | 'categories' | 'errors' | 'harnesses' | 'models'
type FacetToggleKey = 'slow' | 'isNew' | 'gaveFeedback'

const FACET_LISTS: {
    control: McpFacetControl
    key: FacetListKey
    label: string
    searchLabel: string
    options: (facets: McpFacets | null) => string[]
}[] = [
    { control: 'tool', key: 'tools', label: 'Tool', searchLabel: 'tools', options: (f) => optionValues(f?.tools) },
    {
        control: 'category',
        key: 'categories',
        label: 'Category',
        searchLabel: 'categories',
        options: (f) => optionValues(f?.categories),
    },
    {
        control: 'errors',
        key: 'errors',
        label: 'Errors',
        searchLabel: 'errors',
        options: (f) => optionValues(f?.errorTypes),
    },
    {
        control: 'harness',
        key: 'harnesses',
        label: 'Harness',
        searchLabel: 'harnesses',
        options: (f) => optionValues(f?.harnesses),
    },
    { control: 'model', key: 'models', label: 'Model', searchLabel: 'models', options: (f) => optionValues(f?.models) },
]

// pinned: the data-attr suffixes predate this menu, so autocapture keeps counting the same clicks.
const FACET_TOGGLES: {
    control: McpFacetControl
    key: FacetToggleKey
    label: string
    icon: ReactNode
    tooltip: string
    dataAttr: string
}[] = [
    {
        control: 'slow',
        key: 'slow',
        label: 'Slow',
        icon: <IconHourglass />,
        tooltip: 'Calls slower than the p95 of all calls in the last 30 days',
        dataAttr: 'slow',
    },
    {
        control: 'isNew',
        key: 'isNew',
        label: 'New tools',
        icon: <IconSparkles />,
        tooltip: 'Calls to tools first called in this date range, with no calls in the 90 days before',
        dataAttr: 'new',
    },
    {
        control: 'feedback',
        key: 'gaveFeedback',
        label: 'Missing capability',
        icon: <IconPlug />,
        tooltip: 'Calls from sessions where the agent reported a missing capability',
        dataAttr: 'feedback',
    },
]

function optionValues(options: { value: string }[] | undefined): string[] {
    return (options ?? []).map((option) => option.value)
}

/** One menu for the MCP facets. Active facets show next to it, so they stay visible and easy to remove. */
export function McpQuickFilters({
    facetControls,
    dataAttrPrefix,
    pageFilters,
}: {
    facetControls: readonly McpFacetControl[]
    dataAttrPrefix: string
    pageFilters?: McpPageQuickFilters
}): JSX.Element {
    const { facetFilters } = useValues(mcpAnalyticsFiltersLogic)
    const { setFacetFilters } = useActions(mcpAnalyticsFiltersLogic)
    const { facets } = useValues(mcpFacetsLogic)

    const lists: McpQuickFilterList[] = [
        ...FACET_LISTS.filter(
            (list) =>
                facetControls.includes(list.control) &&
                // Categories are an optional SDK field, so the filter hides when no call has one.
                (list.key !== 'categories' || list.options(facets).length > 0 || facetFilters.categories.length > 0)
        ).map((list) => ({
            key: list.key,
            label: list.label,
            searchLabel: list.searchLabel,
            options: list.options(facets),
            value: facetFilters[list.key],
            onChange: (value: string[]) => setFacetFilters({ [list.key]: value } as Partial<McpFacetFilters>),
            dataAttr: list.control,
        })),
        ...(pageFilters?.lists ?? []),
    ]
    const toggles: McpQuickFilterToggle[] = [
        ...FACET_TOGGLES.filter((toggle) => facetControls.includes(toggle.control)).map((toggle) => ({
            ...toggle,
            value: facetFilters[toggle.key],
            onChange: (value: boolean) => setFacetFilters({ [toggle.key]: value }),
            disabledReason:
                toggle.key === 'slow' && !facets?.p95 && !facetFilters.slow
                    ? 'Needs calls from the last 30 days to set the slow threshold'
                    : undefined,
        })),
        ...(pageFilters?.toggles ?? []),
    ]
    const activeLists = lists.filter((list) => list.value.length > 0)
    const activeToggles = toggles.filter((toggle) => toggle.value)
    const activeCount = activeLists.length + activeToggles.length
    const clearAll = (): void => {
        setFacetFilters(DEFAULT_FACET_FILTERS)
        pageFilters?.lists?.forEach((list) => list.onChange([]))
        pageFilters?.toggles?.forEach((toggle) => toggle.onChange(false))
    }

    return (
        <>
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button
                            variant="outline"
                            className={cn('gap-1.5', activeCount > 0 && MCP_FILTER_ACTIVE_CLASS)}
                            data-attr={`${dataAttrPrefix}-quick-filters`}
                        />
                    }
                >
                    <IconFilter />
                    Quick filters
                    {activeCount > 0 ? <span className="tabular-nums">({activeCount})</span> : null}
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="w-56">
                    {lists.map((list) => {
                        // A selected value that dropped out of the window still shows, so it can be cleared.
                        const items = [...list.value.filter((value) => !list.options.includes(value)), ...list.options]
                        return (
                            <DropdownMenuFilterProvider key={list.key} autoHighlight>
                                <DropdownMenuSub>
                                    <DropdownMenuSubTrigger
                                        data-attr={`${dataAttrPrefix}-quick-filter-${list.dataAttr}`}
                                    >
                                        {list.label}
                                        {list.value.length > 0 ? (
                                            <span className="ml-auto tabular-nums text-secondary">
                                                {list.value.length}
                                            </span>
                                        ) : null}
                                    </DropdownMenuSubTrigger>
                                    <DropdownMenuSubContent className="w-64" flush>
                                        <DropdownMenuInput
                                            placeholder={`Search ${list.searchLabel}`}
                                            aria-label={`Search ${list.searchLabel}`}
                                        />
                                        <DropdownMenuEmpty>No matches</DropdownMenuEmpty>
                                        <DropdownMenuList className="max-h-80 overflow-y-auto">
                                            {items.map((item) => (
                                                <DropdownMenuCheckboxItem
                                                    key={item}
                                                    // Values are raw event data, so keep them out of autocapture and replay.
                                                    className="ph-no-capture"
                                                    checked={list.value.includes(item)}
                                                    onCheckedChange={(checked: boolean) =>
                                                        list.onChange(
                                                            checked
                                                                ? [...list.value, item]
                                                                : list.value.filter((v) => v !== item)
                                                        )
                                                    }
                                                >
                                                    <span className="truncate">{item}</span>
                                                </DropdownMenuCheckboxItem>
                                            ))}
                                        </DropdownMenuList>
                                    </DropdownMenuSubContent>
                                </DropdownMenuSub>
                            </DropdownMenuFilterProvider>
                        )
                    })}
                    {lists.length > 0 && toggles.length > 0 ? <DropdownMenuSeparator /> : null}
                    {toggles.map((toggle) => (
                        <DropdownMenuCheckboxItem
                            key={toggle.key}
                            checked={toggle.value}
                            onCheckedChange={(checked: boolean) => toggle.onChange(checked)}
                            tooltip={toggle.disabledReason ? undefined : toggle.tooltip}
                            disabledReason={toggle.disabledReason}
                            data-attr={`${dataAttrPrefix}-filter-${toggle.dataAttr}`}
                        >
                            {toggle.label}
                        </DropdownMenuCheckboxItem>
                    ))}
                    {activeCount > 0 ? (
                        <>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem onClick={clearAll} data-attr={`${dataAttrPrefix}-clear-quick-filters`}>
                                Clear quick filters
                            </DropdownMenuItem>
                        </>
                    ) : null}
                </DropdownMenuContent>
            </DropdownMenu>
            {activeLists.map((list) => (
                <McpFacetSelect
                    key={list.key}
                    label={list.label}
                    searchLabel={list.searchLabel}
                    options={list.options.map((value) => ({ value, calls: 0 }))}
                    value={list.value}
                    onChange={list.onChange}
                    dataAttr={`${dataAttrPrefix}-filter-${list.dataAttr}`}
                />
            ))}
            {activeToggles.map((toggle) => (
                <Button
                    key={toggle.key}
                    variant="outline"
                    className={cn('gap-1.5', MCP_FILTER_ACTIVE_CLASS)}
                    onClick={() => toggle.onChange(false)}
                    aria-label={`Remove the ${toggle.label} filter`}
                    title={toggle.tooltip}
                    data-attr={`${dataAttrPrefix}-filter-${toggle.dataAttr}-remove`}
                >
                    {toggle.icon}
                    {toggle.label}
                    <IconX className="text-secondary" />
                </Button>
            ))}
        </>
    )
}
