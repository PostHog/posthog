import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'

import { Facet, FacetOption } from './Facet'
import { facetFilterTarget, facetSelection } from './facetFilters'
import { facetRailLogic } from './facetRailLogic'
import { FacetConfig, mergeSelectedIntoOptions } from './facets'
import { facetValuesLogic } from './facetValuesLogic'

export interface RailFacetProps {
    id: string
    facet: FacetConfig
    /**
     * Filtered out by the rail's facet-name search. Renders nothing, but keeps this facet's logic
     * mounted — clearing the search box shouldn't cost a round trip to redraw values we already had.
     */
    hidden?: boolean
}

/** One facet in the rail, with its own independently-loaded values (see facetValuesLogic). */
export function RailFacet({ id, facet, hidden }: RailFacetProps): JSX.Element | null {
    // `facet` comes from the memoized visibleFacets selector, so this identity is stable.
    const logicProps = useMemo(() => ({ id, facet }), [id, facet])
    const { facetValues, facetValuesLoading, facetSearch, collapsed } = useValues(facetValuesLogic(logicProps))
    const { setFacetSearch } = useActions(facetValuesLogic(logicProps))
    const { filterGroup } = useValues(logsViewerFiltersLogic({ id }))
    const { toggleFacetValue, toggleFacetCollapsed } = useActions(facetRailLogic({ id }))

    if (hidden) {
        return null
    }

    const { source } = facet
    // Both polarities come from the facet's own filters in the group, which is also what the chips
    // bar renders, so a checkbox can't show a state the filter bar contradicts.
    const { included: selected, excluded } = facetSelection(filterGroup, facetFilterTarget(source))
    // Values + counts come from the cross-filtered endpoint.
    const fetched: FacetOption[] = facetValues.map((r) => ({ value: r.value, label: r.value, count: r.count }))
    const onToggle = (value: string): void => toggleFacetValue(source, value)
    const onToggleCollapsed = (): void => toggleFacetCollapsed(facet.key)

    if (facet.kind === 'fixed') {
        // Fixed value set from config, counts overlaid. Missing values render as a dimmed 0.
        const countByValue = new Map(fetched.map((option) => [option.value, option.count]))
        const options: FacetOption[] = (facet.fixedOptions ?? []).map((option) => ({
            ...option,
            count: countByValue.get(option.value) ?? 0,
        }))
        return (
            <Facet
                title={facet.title}
                options={options}
                selected={selected}
                excluded={excluded}
                onToggle={onToggle}
                loading={facetValuesLoading}
                collapsed={collapsed}
                onToggleCollapsed={onToggleCollapsed}
                dimZeroCounts
            />
        )
    }

    // Dynamic facet: values + counts come from the cross-filtered endpoint, plus any selected or
    // excluded values it didn't return (zero matches in scope, or below the top-N cutoff) so an
    // active filter — e.g. from an old saved-view URL — is always visible and removable.
    return (
        <Facet
            title={facet.title}
            options={mergeSelectedIntoOptions(
                fetched,
                [...selected, ...excluded],
                facet.searchable ? facetSearch : undefined
            )}
            selected={selected}
            excluded={excluded}
            onToggle={onToggle}
            loading={facetValuesLoading}
            emptyLabel={facet.emptyLabel}
            searchValue={facet.searchable ? facetSearch : undefined}
            onSearchChange={facet.searchable ? setFacetSearch : undefined}
            searchPlaceholder={facet.searchPlaceholder}
            collapsed={collapsed}
            onToggleCollapsed={onToggleCollapsed}
            maxHeight={facet.maxHeight}
        />
    )
}
