import { useActions, useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'

import { customFacetsLogic } from './customFacetsLogic'
import { Facet, FacetOption } from './Facet'
import { facetFilterTarget, facetSelection } from './facetFilters'
import { facetRailLogic } from './facetRailLogic'
import { FacetConfig, customFacetIdentity, mergeSelectedIntoOptions } from './facets'
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
    const { removeCustomFacet } = useActions(customFacetsLogic)
    const { entriesLoading } = useValues(customFacetsLogic)
    const removeDisabledReason = entriesLoading ? 'Custom facets are updating' : undefined

    const { source } = facet
    // Everything the value rows are built from is memoized: Facet feeds them to a virtualized list
    // through one useMemo, so a fresh array or callback identity here re-renders every visible row in
    // every mounted facet on any filter or count change.
    // Both polarities come from the facet's own filters in the group, which is also what the chips
    // bar renders, so a checkbox can't show a state the filter bar contradicts.
    const { included: selected, excluded } = useMemo(
        () => facetSelection(filterGroup, facetFilterTarget(source)),
        [filterGroup, source]
    )
    // Values + counts come from the cross-filtered endpoint.
    const fetched: FacetOption[] = useMemo(
        () => facetValues.map((r) => ({ value: r.value, label: r.value, count: r.count })),
        [facetValues]
    )
    // Fixed value set from config, counts overlaid. Missing values render as a dimmed 0.
    const fixedOptions: FacetOption[] = useMemo(() => {
        const countByValue = new Map(fetched.map((option) => [option.value, option.count]))
        return (facet.fixedOptions ?? []).map((option) => ({
            ...option,
            count: countByValue.get(option.value) ?? 0,
        }))
    }, [fetched, facet.fixedOptions])
    // Dynamic facet: the fetched values, plus any selected or excluded value the endpoint didn't
    // return (zero matches in scope, or below the top-N cutoff) so an active filter — e.g. from an
    // old saved-view URL — is always visible and removable.
    const dynamicOptions: FacetOption[] = useMemo(
        () => mergeSelectedIntoOptions(fetched, [...selected, ...excluded], facet.searchable ? facetSearch : undefined),
        [fetched, selected, excluded, facet.searchable, facetSearch]
    )
    const onToggle = useCallback((value: string): void => toggleFacetValue(source, value), [toggleFacetValue, source])
    const onToggleCollapsed = useCallback(
        (): void => toggleFacetCollapsed(facet.key),
        [toggleFacetCollapsed, facet.key]
    )
    // Only custom facets carry an identity; curated facets get no remove control.
    const onRemove = useMemo(() => {
        const customIdentity = customFacetIdentity(facet)
        return customIdentity ? (): void => removeCustomFacet(customIdentity.key, customIdentity.sourceType) : undefined
    }, [facet, removeCustomFacet])

    if (hidden) {
        return null
    }

    if (facet.kind === 'fixed') {
        return (
            <Facet
                title={facet.title}
                options={fixedOptions}
                selected={selected}
                excluded={excluded}
                onToggle={onToggle}
                loading={facetValuesLoading}
                collapsed={collapsed}
                onToggleCollapsed={onToggleCollapsed}
                dimZeroCounts
                onRemove={onRemove}
                removeDisabledReason={removeDisabledReason}
            />
        )
    }

    return (
        <Facet
            title={facet.title}
            options={dynamicOptions}
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
            onRemove={onRemove}
            removeDisabledReason={removeDisabledReason}
        />
    )
}
