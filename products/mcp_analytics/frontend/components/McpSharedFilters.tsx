import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconHourglass, IconPlug, IconRefresh, IconSparkles } from '@posthog/icons'
import { Button } from '@posthog/quill-primitives'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { MCP_TOOL_CALL_EVENT } from 'lib/components/TaxonomicFilter/utils/mcpProperties'
import { Toggle, Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'
import { cn } from 'lib/utils/css-classes'

import { DEFAULT_FACET_FILTERS, mcpAnalyticsFiltersLogic } from '../mcpAnalyticsFiltersLogic'
import { mcpFacetsLogic } from '../mcpFacetsLogic'
import { MCP_FILTER_ACTIVE_CLASS, McpFacetSelect } from './McpFacetSelect'
import { McpInternalUsersFilter } from './McpInternalUsersFilter'

const TAXONOMIC_GROUP_TYPES = [
    TaxonomicFilterGroupType.MCPProperties,
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.EventFeatureFlags,
]

// PropertyFilters always renders its add button as a raised LemonButton. These overrides restyle it as a quill
// outline button at the default size, so it matches the other buttons in the row. The values copy the outline
// variant and default size in quill's button.css. They read quill tokens such as --foreground and --radius-sm,
// which exist only inside a data-quill subtree, so the button must render inside one. LemonButton draws its
// border on both ::before and ::after of the chrome element. The quill border color is translucent, so two
// layers make it darker, and the overrides hide the ::before layer. FilterRow renders IconPlusSmall, whose glyph
// fills less of its box than the icons in the other buttons, so the overrides scale it to the same drawn size.
const QUILL_OUTLINE_ADD_FILTER_BUTTON = [
    '*:before:hidden!',
    '[&_svg]:scale-150!',
    '[--lemon-button-chrome-depth:0px]! [--lemon-button-hover-depth:0px]! [--lemon-button-press-depth:0px]! [--lemon-button-frame-bg-color:transparent]!',
    '[--button-border-color:color-mix(in_oklab,var(--foreground)_10%,transparent)]! [--lemon-button-border-color-hover:color-mix(in_oklab,var(--foreground)_10%,transparent)]!',
    'dark:[--button-border-color:color-mix(in_oklab,var(--foreground)_15%,transparent)]! dark:[--lemon-button-border-color-hover:color-mix(in_oklab,var(--foreground)_15%,transparent)]!',
    '[--lemon-button-bg-color:color-mix(in_oklab,var(--muted)_30%,transparent)]! hover:[--lemon-button-bg-color:var(--fill-hover)]!',
    '[--lemon-button-radius:var(--radius-sm)]!',
    '[--lemon-button-height:1.75rem]! [--lemon-button-font-size:0.8125rem]! [--lemon-button-icon-size:0.875rem]! [--lemon-button-padding-vertical:0.125rem]! [--lemon-button-padding-horizontal:0.5rem]! [--lemon-button-padding-adjacent-icon:0.375rem]! [--lemon-button-gap:0.5rem]!',
].join(' ')

// PropertyFilters renders each active filter as a 32px PropertyFilterButton pill. Error tracking, logs, tracing
// and metrics show their filters with UniversalFilterButton instead. These overrides copy the height, padding
// and corner radii from UniversalFilterButton.scss, so the tags here match the tags on those pages.
const UNIVERSAL_FILTER_TAG_ACTIVE_FILTERS = [
    '[&_.PropertyFilterButton]:h-[1.625rem]! [&_.PropertyFilterButton]:py-[0.125rem]! [&_.PropertyFilterButton]:rounded-[0.275rem]!',
    '[&_.PropertyFilterButton_.LemonButton]:rounded-[0.25rem]!',
].join(' ')

export type McpFacetControl = 'tool' | 'category' | 'errors' | 'harness' | 'model' | 'slow' | 'isNew' | 'feedback'

const ALL_FACET_CONTROLS: readonly McpFacetControl[] = [
    'tool',
    'category',
    'errors',
    'harness',
    'model',
    'slow',
    'isNew',
    'feedback',
]

interface McpSharedFiltersProps {
    pageKey: string
    dataAttrPrefix: string
    className?: string
    /** The page's search and date range, which lead the row. */
    children?: ReactNode
    /** Whether the page's own filters are set, so "Clear filters" shows for them too. */
    hasPageFilters?: boolean
    onClearPageFilters?: () => void
    onRefresh: () => void
    refreshing: boolean
    /** A tab whose data lacks a facet's property leaves it out. */
    facetControls?: readonly McpFacetControl[]
    /** Filters only this tab has, shown after the shared facets. */
    pageFacets?: ReactNode
}

export function McpSharedFilters({
    pageKey,
    dataAttrPrefix,
    className,
    children,
    hasPageFilters = false,
    onClearPageFilters,
    onRefresh,
    refreshing,
    facetControls = ALL_FACET_CONTROLS,
    pageFacets,
}: McpSharedFiltersProps): JSX.Element {
    const shows = (control: McpFacetControl): boolean => facetControls.includes(control)
    const { propertyFilters, facetFilters, hasActiveFacetFilters } = useValues(mcpAnalyticsFiltersLogic)
    const { setPropertyFilters, setFacetFilters } = useActions(mcpAnalyticsFiltersLogic)
    const { facets } = useValues(mcpFacetsLogic)

    return (
        <div className={cn('w-full min-w-0', className)} data-attr={`${dataAttrPrefix}-property-filter`}>
            <PropertyFilters
                pageKey={pageKey}
                propertyFilters={propertyFilters}
                onChange={setPropertyFilters}
                taxonomicGroupTypes={TAXONOMIC_GROUP_TYPES}
                eventNames={[MCP_TOOL_CALL_EVENT]}
                buttonText="Add filter"
                buttonClassName={QUILL_OUTLINE_ADD_FILTER_BUTTON}
                buttonSize="small"
                renderControls={({ addFilter, activeFilters, clearFilters }) => (
                    <div className="flex w-full min-w-0 flex-col gap-2">
                        <div className="flex flex-wrap items-center gap-2">
                            {children}
                            <div data-quill className="contents">
                                {addFilter}
                            </div>
                            {shows('tool') && (
                                <McpFacetSelect
                                    label="Tool"
                                    options={facets?.tools ?? []}
                                    value={facetFilters.tools}
                                    onChange={(tools) => setFacetFilters({ tools })}
                                    dataAttr={`${dataAttrPrefix}-filter-tool`}
                                />
                            )}
                            {/* Categories are an optional SDK field, so the filter hides when no call has one. */}
                            {shows('category') && (facets?.categories.length || facetFilters.categories.length) ? (
                                <McpFacetSelect
                                    label="Category"
                                    options={facets?.categories ?? []}
                                    value={facetFilters.categories}
                                    onChange={(categories) => setFacetFilters({ categories })}
                                    dataAttr={`${dataAttrPrefix}-filter-category`}
                                />
                            ) : null}
                            {shows('errors') && (
                                <McpFacetSelect
                                    label="Errors"
                                    options={facets?.errorTypes ?? []}
                                    value={facetFilters.errors}
                                    onChange={(errors) => setFacetFilters({ errors })}
                                    dataAttr={`${dataAttrPrefix}-filter-errors`}
                                />
                            )}
                            {shows('harness') && (
                                <McpFacetSelect
                                    label="Harness"
                                    options={facets?.harnesses ?? []}
                                    value={facetFilters.harnesses}
                                    onChange={(harnesses) => setFacetFilters({ harnesses })}
                                    dataAttr={`${dataAttrPrefix}-filter-harness`}
                                />
                            )}
                            {shows('model') && (
                                <McpFacetSelect
                                    label="Model"
                                    options={facets?.models ?? []}
                                    value={facetFilters.models}
                                    onChange={(models) => setFacetFilters({ models })}
                                    dataAttr={`${dataAttrPrefix}-filter-model`}
                                />
                            )}
                            {shows('slow') && (
                                <Tooltip>
                                    <TooltipTrigger
                                        render={
                                            <Toggle
                                                variant="outline"
                                                pressed={facetFilters.slow}
                                                disabled={!facets?.p95 && !facetFilters.slow}
                                                onPressedChange={(slow: boolean) => setFacetFilters({ slow })}
                                                className={cn(facetFilters.slow && MCP_FILTER_ACTIVE_CLASS)}
                                                data-attr={`${dataAttrPrefix}-filter-slow`}
                                            />
                                        }
                                    >
                                        <IconHourglass />
                                        Slow
                                    </TooltipTrigger>
                                    <TooltipContent>
                                        Calls slower than the p95 of all calls in the last 30 days
                                    </TooltipContent>
                                </Tooltip>
                            )}
                            {shows('isNew') && (
                                <Tooltip>
                                    <TooltipTrigger
                                        render={
                                            <Toggle
                                                variant="outline"
                                                pressed={facetFilters.isNew}
                                                onPressedChange={(isNew: boolean) => setFacetFilters({ isNew })}
                                                className={cn(facetFilters.isNew && MCP_FILTER_ACTIVE_CLASS)}
                                                data-attr={`${dataAttrPrefix}-filter-new`}
                                            />
                                        }
                                    >
                                        <IconSparkles />
                                        New tools
                                    </TooltipTrigger>
                                    <TooltipContent>
                                        Calls to tools first called in this date range, with no calls in the 90 days
                                        before
                                    </TooltipContent>
                                </Tooltip>
                            )}
                            {shows('feedback') && (
                                <Tooltip>
                                    <TooltipTrigger
                                        render={
                                            <Toggle
                                                variant="outline"
                                                pressed={facetFilters.gaveFeedback}
                                                onPressedChange={(gaveFeedback: boolean) =>
                                                    setFacetFilters({ gaveFeedback })
                                                }
                                                className={cn(facetFilters.gaveFeedback && MCP_FILTER_ACTIVE_CLASS)}
                                                data-attr={`${dataAttrPrefix}-filter-feedback`}
                                            />
                                        }
                                    >
                                        <IconPlug />
                                        Missing capability
                                    </TooltipTrigger>
                                    <TooltipContent>
                                        Calls from sessions where the agent reported a missing capability
                                    </TooltipContent>
                                </Tooltip>
                            )}
                            {pageFacets}
                            {(activeFilters.length > 0 || hasActiveFacetFilters || hasPageFilters) && (
                                <Button
                                    variant="link-muted"
                                    size="sm"
                                    onClick={() => {
                                        if (activeFilters.length > 0) {
                                            clearFilters()
                                        }
                                        if (hasActiveFacetFilters) {
                                            setFacetFilters(DEFAULT_FACET_FILTERS)
                                        }
                                        onClearPageFilters?.()
                                    }}
                                    data-attr={`${dataAttrPrefix}-clear-filters`}
                                >
                                    Clear filters
                                </Button>
                            )}
                            <div className="ml-auto flex items-center gap-2">
                                <McpInternalUsersFilter dataAttr={`${dataAttrPrefix}-test-account-filter`} />
                                <Button
                                    variant="outline"
                                    size="icon"
                                    onClick={onRefresh}
                                    loading={refreshing}
                                    aria-label="Refresh"
                                    title="Refresh"
                                    data-attr={`${dataAttrPrefix}-refresh`}
                                >
                                    <IconRefresh />
                                </Button>
                            </div>
                        </div>
                        {activeFilters.length > 0 && (
                            <div
                                className={cn(
                                    'flex min-w-0 flex-wrap items-center gap-2',
                                    UNIVERSAL_FILTER_TAG_ACTIVE_FILTERS
                                )}
                            >
                                {activeFilters}
                            </div>
                        )}
                    </div>
                )}
            />
        </div>
    )
}
