import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useMemo, useRef } from 'react'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'

import { logsViewerConfigLogic } from 'products/logs/frontend/components/LogsViewer/config/logsViewerConfigLogic'
import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'
import { serviceFilterLogic } from 'products/logs/frontend/components/LogsViewer/Filters/serviceFilterLogic'

import { Facet, FacetOption } from './Facet'
import { facetCountsLogic } from './facetCountsLogic'
import { facetRailLogic } from './facetRailLogic'
import { FacetConfig, FacetFilterKey, FacetField, facetsByGroup } from './facets'

const DEFAULT_WIDTH_PX = 240
const COLLAPSE_THRESHOLD_PX = 120

export interface FacetRailProps {
    id: string
}

/** Resizable left-hand facet rail, rendered entirely from the FACETS config (see facets.ts). */
export function FacetRail({ id }: FacetRailProps): JSX.Element {
    const railRef = useRef<HTMLDivElement>(null)
    const { setFacetRailCollapsed } = useActions(logsViewerConfigLogic)
    const { severityLevels, serviceNames, utcDateRange } = useValues(logsViewerFiltersLogic)
    const { levelCounts, serviceCounts } = useValues(facetCountsLogic({ id }))
    const { collapsedFacets } = useValues(facetRailLogic({ id }))
    const { toggleFacetValue, toggleFacetCollapsed } = useActions(facetRailLogic({ id }))

    const selectedByKey: Record<FacetFilterKey, string[]> = {
        severityLevels: severityLevels ?? [],
        serviceNames: serviceNames ?? [],
    }
    const countsByField: Record<FacetField, Record<string, number>> = {
        severity_text: levelCounts,
        service_name: serviceCounts,
    }

    const onToggleClosed = useCallback(
        (shouldBeClosed: boolean) => setFacetRailCollapsed(shouldBeClosed),
        [setFacetRailCollapsed]
    )
    const resizerLogicProps: ResizerLogicProps = useMemo(
        () => ({
            logicKey: `logs-facet-rail-${id}`,
            containerRef: railRef,
            persistent: true,
            persistPrefix: '2026-06-18',
            placement: 'right',
            closeThreshold: COLLAPSE_THRESHOLD_PX,
            onToggleClosed,
        }),
        [id, onToggleClosed]
    )
    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    const renderFacet = (facet: FacetConfig): JSX.Element => {
        const selected = selectedByKey[facet.filterKey]
        const counts = countsByField[facet.facetField] ?? {}
        const shared = {
            facet,
            selected,
            counts,
            collapsed: collapsedFacets.includes(facet.key),
            onToggle: (value: string) => toggleFacetValue(facet.filterKey, value),
            onToggleCollapsed: () => toggleFacetCollapsed(facet.key),
        }
        if (facet.kind === 'dynamic') {
            return (
                <BindLogic key={facet.key} logic={serviceFilterLogic} props={{ dateRange: utcDateRange }}>
                    <DynamicFacet {...shared} />
                </BindLogic>
            )
        }
        return <FixedFacet key={facet.key} {...shared} />
    }

    return (
        <div
            ref={railRef}
            className="relative flex flex-col shrink-0 border rounded bg-surface-primary overflow-hidden"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width: desiredSize ?? DEFAULT_WIDTH_PX, minWidth: 'min-content', maxWidth: '40%' }}
            data-attr="logs-facet-rail"
        >
            <div className="px-2 py-1 border-b">
                <span className="text-xs font-semibold text-secondary uppercase tracking-wide">Filters</span>
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto p-2">
                {facetsByGroup().map(([group, facets]) => (
                    <div key={group}>
                        <div className="px-1 pb-1 mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted border-b border-primary">
                            {group}
                        </div>
                        {facets.map(renderFacet)}
                    </div>
                ))}
            </div>
            <Resizer {...resizerLogicProps} visible={false} offset="0.25rem" handleClassName="rounded my-1" />
        </div>
    )
}

interface FacetRenderProps {
    facet: FacetConfig
    selected: string[]
    counts: Record<string, number>
    collapsed: boolean
    onToggle: (value: string) => void
    onToggleCollapsed: () => void
}

/** Fixed facet: the closed value set from config, with counts overlaid. */
function FixedFacet({
    facet,
    selected,
    counts,
    collapsed,
    onToggle,
    onToggleCollapsed,
}: FacetRenderProps): JSX.Element {
    const options: FacetOption[] = (facet.fixedOptions ?? []).map((option) => ({
        ...option,
        count: counts[option.value],
    }))
    return (
        <Facet
            title={facet.title}
            options={options}
            selected={selected}
            onToggle={onToggle}
            collapsed={collapsed}
            onToggleCollapsed={onToggleCollapsed}
        />
    )
}

/** Dynamic facet: values discovered from the data. PR1 keeps the service list/search on serviceFilterLogic. */
function DynamicFacet({
    facet,
    selected,
    counts,
    collapsed,
    onToggle,
    onToggleCollapsed,
}: FacetRenderProps): JSX.Element {
    const { serviceNames, allServiceNamesLoading, search } = useValues(serviceFilterLogic)
    const { setSearch } = useActions(serviceFilterLogic)

    const options: FacetOption[] = serviceNames.map((name) => ({ value: name, label: name, count: counts[name] }))

    return (
        <Facet
            title={facet.title}
            options={options}
            selected={selected}
            onToggle={onToggle}
            loading={allServiceNamesLoading}
            emptyLabel={facet.emptyLabel}
            searchValue={facet.searchable ? search : undefined}
            onSearchChange={facet.searchable ? setSearch : undefined}
            searchPlaceholder={facet.searchPlaceholder}
            collapsed={collapsed}
            onToggleCollapsed={onToggleCollapsed}
            maxHeight={facet.maxHeight}
        />
    )
}
