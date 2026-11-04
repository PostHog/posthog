import { useActions, useValues } from 'kea'

import { FacetRail } from 'lib/components/FacetRail/FacetRail'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { logsViewerConfigLogic } from 'products/logs/frontend/components/LogsViewer/config/logsViewerConfigLogic'

import { facetPresenceLogic } from './facetPresenceLogic'
import { facetRailLogic } from './facetRailLogic'
import { RailFacet } from './RailFacet'

const ADD_FACET_GROUP_TYPES = {
    attribute: TaxonomicFilterGroupType.LogAttributes,
    resourceAttribute: TaxonomicFilterGroupType.LogResourceAttributes,
}

export interface LogsFacetRailProps {
    id: string
}

/** The logs viewer's facet rail, rendered entirely from the FACETS config (see facets.ts). */
export function LogsFacetRail({ id }: LogsFacetRailProps): JSX.Element {
    const { setFacetRailCollapsed } = useActions(logsViewerConfigLogic)
    const { visibleFacets } = useValues(facetPresenceLogic({ id }))
    const { facetNameSearch } = useValues(facetRailLogic({ id }))
    const { setFacetNameSearch } = useActions(facetRailLogic({ id }))

    return (
        <FacetRail
            product="logs"
            facets={visibleFacets}
            renderFacet={(facet, hidden) => <RailFacet id={id} facet={facet} hidden={hidden} />}
            facetNameSearch={facetNameSearch}
            onFacetNameSearchChange={setFacetNameSearch}
            onCollapsedChange={setFacetRailCollapsed}
            addFacetGroupTypes={ADD_FACET_GROUP_TYPES}
            resizerLogicKey={`logs-facet-rail-${id}`}
            resizerPersistPrefix="2026-06-18"
            dataAttrPrefix="logs-facet-rail"
        />
    )
}
