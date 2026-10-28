import { useActions, useValues } from 'kea'

import { Facet } from 'lib/components/FacetRail/Facet'
import { mergeSelectedIntoOptions } from 'lib/components/FacetRail/facetGroups'

import { metricsViewerLogic } from '../metricsViewerLogic'
import { MetricFacetConfig, metricFacetSelection } from './facets'
import { metricsFacetRailLogic } from './metricsFacetRailLogic'
import { metricsFacetValuesLogic } from './metricsFacetValuesLogic'

/** One metric attribute in the rail. A facet that the name search hides renders nothing, but its logic stays mounted. */
export function RailFacet({ facet, hidden }: { facet: MetricFacetConfig; hidden: boolean }): JSX.Element | null {
    const { facetValues, facetValuesLoading, fetchFailed, facetSearch, collapsed } = useValues(
        metricsFacetValuesLogic({ facet })
    )
    const { setFacetSearch, retryFacetValues } = useActions(metricsFacetValuesLogic({ facet }))
    const { filterGroup } = useValues(metricsViewerLogic)
    const { toggleFacetValue, toggleFacetCollapsed } = useActions(metricsFacetRailLogic)

    if (hidden) {
        return null
    }

    const { included, excluded } = metricFacetSelection(filterGroup, facet.attributeKey)
    return (
        <Facet
            title={facet.title}
            options={mergeSelectedIntoOptions(facetValues, [...included, ...excluded], facetSearch)}
            selected={included}
            excluded={excluded}
            onToggle={(value) => toggleFacetValue(facet.attributeKey, value)}
            dataAttrPrefix="metrics-facet"
            zeroCountReason="No data points of this metric have this value in this time range"
            loading={facetValuesLoading}
            emptyLabel={`No ${facet.title} values`}
            searchValue={facetSearch}
            onSearchChange={setFacetSearch}
            searchPlaceholder="Search values…"
            collapsed={collapsed}
            onToggleCollapsed={() => toggleFacetCollapsed(facet.key)}
            maxHeight={300}
            error={fetchFailed}
            onRetry={retryFacetValues}
        />
    )
}
