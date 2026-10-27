import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { FacetRail } from 'lib/components/FacetRail/FacetRail'

import { metricsFacetRailLogic } from './metricsFacetRailLogic'
import { RailFacet } from './RailFacet'

/** The metrics viewer's facet rail: the service and every attribute the active metric carries. */
export function MetricsFacetRail(): JSX.Element | null {
    const {
        visibleFacets,
        facetNameSearch,
        railCollapsed,
        attributeKeysFailed,
        attributeKeysLoading,
        loadedAttributeKeysScope,
        attributeKeysScope,
    } = useValues(metricsFacetRailLogic)
    const { setFacetNameSearch, setRailCollapsed, retryAttributeKeys } = useActions(metricsFacetRailLogic)

    if (railCollapsed) {
        return null
    }
    return (
        <FacetRail
            notice={
                attributeKeysFailed &&
                !attributeKeysLoading && (
                    <div className="px-1 pb-2 text-xs text-secondary" data-attr="metrics-facet-rail-keys-error">
                        {loadedAttributeKeysScope === attributeKeysScope
                            ? "Couldn't refresh this metric's attributes."
                            : "Couldn't load this metric's attributes."}{' '}
                        <Link onClick={retryAttributeKeys} data-attr="metrics-facet-rail-keys-retry">
                            Retry
                        </Link>
                    </div>
                )
            }
            facets={visibleFacets}
            renderFacet={(facet, hidden) => <RailFacet facet={facet} hidden={hidden} />}
            facetNameSearch={facetNameSearch}
            onFacetNameSearchChange={setFacetNameSearch}
            onCollapsedChange={setRailCollapsed}
            resizerLogicKey="metrics-facet-rail"
            resizerPersistPrefix="2026-10-14"
            dataAttrPrefix="metrics-facet-rail"
        />
    )
}

export function MetricsFacetRailToggle(): JSX.Element {
    const { railCollapsed } = useValues(metricsFacetRailLogic)
    const { setRailCollapsed } = useActions(metricsFacetRailLogic)

    return (
        <LemonButton
            size="small"
            type="secondary"
            icon={railCollapsed ? <IconChevronRight /> : <IconChevronLeft />}
            onClick={() => setRailCollapsed(!railCollapsed)}
            data-attr="metrics-facet-rail-toggle"
        >
            {railCollapsed ? 'Show filters' : 'Hide filters'}
        </LemonButton>
    )
}

/** Puts the rail beside the viewer, with the viewer scrolling on its own so the rail keeps its height. */
export function MetricsFacetRailLayout({ enabled, children }: { enabled: boolean; children: ReactNode }): JSX.Element {
    if (!enabled) {
        return <div className="flex flex-col gap-3">{children}</div>
    }
    return (
        <div className="flex gap-2 flex-1 min-h-0">
            <MetricsFacetRail />
            <div className="flex flex-col gap-3 flex-1 min-w-0 min-h-0 overflow-y-auto">{children}</div>
        </div>
    )
}
