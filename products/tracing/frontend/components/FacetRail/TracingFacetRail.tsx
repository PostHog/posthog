import { useActions, useValues } from 'kea'

import { FacetRail } from 'lib/components/FacetRail/FacetRail'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { tracingConfigLogic } from '../../tracingConfigLogic'
import { facetPresenceLogic } from './facetPresenceLogic'
import { facetRailLogic } from './facetRailLogic'
import { RailFacet } from './RailFacet'

const ADD_FACET_GROUP_TYPES = {
    attribute: TaxonomicFilterGroupType.SpanAttributes,
    resourceAttribute: TaxonomicFilterGroupType.SpanResourceAttributes,
}

/** The tracing scene's facet rail, rendered entirely from the FACETS config (see facets.ts). */
export function TracingFacetRail(): JSX.Element {
    const { setFacetRailCollapsed } = useActions(tracingConfigLogic)
    const { visibleFacets } = useValues(facetPresenceLogic)
    const { facetNameSearch } = useValues(facetRailLogic)
    const { setFacetNameSearch } = useActions(facetRailLogic)

    return (
        <FacetRail
            product="tracing"
            facets={visibleFacets}
            renderFacet={(facet, hidden) => <RailFacet facet={facet} hidden={hidden} />}
            facetNameSearch={facetNameSearch}
            onFacetNameSearchChange={setFacetNameSearch}
            onCollapsedChange={setFacetRailCollapsed}
            addFacetGroupTypes={ADD_FACET_GROUP_TYPES}
            resizerLogicKey="tracing-facet-rail"
            resizerPersistPrefix="2026-07-06"
            dataAttrPrefix="tracing-facet-rail"
        />
    )
}
