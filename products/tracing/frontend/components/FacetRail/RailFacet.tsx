import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { TRACING_SCENE_VIEWER_ID, tracingFiltersLogic } from 'products/tracing/frontend/tracingFiltersLogic'

import { customFacetsLogic } from './customFacetsLogic'
import { Facet } from './Facet'
import { facetRailLogic } from './facetRailLogic'
import {
    FacetConfig,
    FacetOption,
    customFacetIdentity,
    facetSelection,
    facetValueGroup,
    mergeSelectedIntoOptions,
} from './facets'
import { facetValuesLogic } from './facetValuesLogic'

export interface RailFacetProps {
    facet: FacetConfig
    id?: string
    /**
     * Filtered out by the rail's facet-name search. Renders nothing, but keeps this facet's logic
     * mounted — clearing the search box shouldn't cost a round trip to redraw values we already had.
     */
    hidden?: boolean
}

/** One facet in the rail, with its own independently-loaded values (see facetValuesLogic). */
export function RailFacet({ facet, id = TRACING_SCENE_VIEWER_ID, hidden }: RailFacetProps): JSX.Element | null {
    // `facet` comes from the memoized visibleFacets selector, so this identity is stable.
    const logicProps = useMemo(() => ({ id, facet }), [id, facet])
    const { facetValues, facetValuesLoading, fetchFailed, facetSearch, collapsed } = useValues(
        facetValuesLogic(logicProps)
    )
    const { setFacetSearch } = useActions(facetValuesLogic(logicProps))
    const { serviceNames, filters } = useValues(tracingFiltersLogic({ id }))
    const { toggleFacetValue, toggleFacetCollapsed } = useActions(facetRailLogic({ id }))
    const { removeCustomFacet } = useActions(customFacetsLogic)
    const { entriesLoading } = useValues(customFacetsLogic)
    const removeDisabledReason = entriesLoading ? 'Custom facets are updating' : undefined

    if (hidden) {
        return null
    }

    const { source } = facet
    // Selection: the service facet reads the dedicated serviceNames field (include-only);
    // everything else reads its property filters out of the group, both polarities.
    const { included: selected, excluded } = facetSelection(filters.filterGroup, serviceNames, source)
    // Drop the empty-value bucket (spans missing the attribute): it renders as a blank, label-less row
    // that the selection reader can't track, so it would become a stuck, un-toggleable filter.
    const fetched: FacetOption[] = facetValues
        .filter((row) => row.value !== '')
        .map((row) => ({ value: row.value, label: row.value, count: row.count }))
    const onToggle = (value: string): void => toggleFacetValue(source, value)
    const onToggleCollapsed = (): void => toggleFacetCollapsed(facet.key)
    const customIdentity = customFacetIdentity(facet)
    const onRemove = customIdentity
        ? (): void => removeCustomFacet(customIdentity.key, customIdentity.sourceType)
        : undefined

    if (facet.kind === 'fixed') {
        // Fixed value set from config, counts overlaid. Missing values render as a dimmed 0.
        const countByValue = new Map(fetched.map((option) => [option.value, option.count]))
        const options: FacetOption[] = (facet.fixedOptions ?? []).map((option) => ({
            ...option,
            count: facetValueGroup(source, option.value).reduce((sum, v) => sum + (countByValue.get(v) ?? 0), 0),
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
                error={fetchFailed}
                onRemove={onRemove}
                removeDisabledReason={removeDisabledReason}
            />
        )
    }

    // Dynamic facet: values + counts come straight from the cross-filtered endpoint (zeros never
    // appear), with any selected-but-absent values injected so they stay visible and toggleable.
    const search = facet.searchable ? facetSearch : undefined
    return (
        <Facet
            title={facet.title}
            options={mergeSelectedIntoOptions(fetched, [...selected, ...excluded], search)}
            selected={selected}
            excluded={excluded}
            onToggle={onToggle}
            loading={facetValuesLoading}
            emptyLabel={facet.emptyLabel}
            searchValue={search}
            onSearchChange={facet.searchable ? setFacetSearch : undefined}
            searchPlaceholder={facet.searchPlaceholder}
            collapsed={collapsed}
            onToggleCollapsed={onToggleCollapsed}
            maxHeight={facet.maxHeight}
            error={fetchFailed}
            onRemove={onRemove}
            removeDisabledReason={removeDisabledReason}
        />
    )
}
