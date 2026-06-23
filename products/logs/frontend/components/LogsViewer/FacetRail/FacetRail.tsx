import { useActions, useValues } from 'kea'
import { useCallback, useMemo, useRef } from 'react'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'

import { logsViewerConfigLogic } from 'products/logs/frontend/components/LogsViewer/config/logsViewerConfigLogic'
import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'

import { Facet, FacetOption } from './Facet'
import { facetCountsLogic } from './facetCountsLogic'
import { facetRailLogic } from './facetRailLogic'
import { FacetConfig, FacetField, FacetFilterKey, facetsByGroup } from './facets'

const DEFAULT_WIDTH_PX = 240
const COLLAPSE_THRESHOLD_PX = 120

export interface FacetRailProps {
    id: string
}

/** Resizable left-hand facet rail, rendered entirely from the FACETS config (see facets.ts). */
export function FacetRail({ id }: FacetRailProps): JSX.Element {
    const railRef = useRef<HTMLDivElement>(null)
    const { setFacetRailCollapsed } = useActions(logsViewerConfigLogic)
    const { severityLevels, serviceNames } = useValues(logsViewerFiltersLogic)
    const { levelValues, levelValuesLoading, serviceValues, serviceValuesLoading, facetSearch } = useValues(
        facetCountsLogic({ id })
    )
    const { setFacetSearch } = useActions(facetCountsLogic({ id }))
    const { collapsedFacets } = useValues(facetRailLogic({ id }))
    const { toggleFacetValue, toggleFacetCollapsed } = useActions(facetRailLogic({ id }))

    const selectedByKey: Record<FacetFilterKey, string[]> = {
        severityLevels: severityLevels ?? [],
        serviceNames: serviceNames ?? [],
    }
    const valuesByField: Record<FacetField, FacetOption[]> = {
        severity_text: levelValues.map((r) => ({ value: r.value, label: r.value, count: r.count })),
        service_name: serviceValues.map((r) => ({ value: r.value, label: r.value, count: r.count })),
    }
    const loadingByField: Record<FacetField, boolean> = {
        severity_text: levelValuesLoading,
        service_name: serviceValuesLoading,
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
        const fetched = valuesByField[facet.facetField]
        const onToggle = (value: string): void => toggleFacetValue(facet.filterKey, value)
        const onToggleCollapsed = (): void => toggleFacetCollapsed(facet.key)
        const collapsed = collapsedFacets.includes(facet.key)

        if (facet.kind === 'fixed') {
            // Fixed value set from config, counts overlaid. Missing values render as a dimmed 0.
            const countByValue = new Map(fetched.map((option) => [option.value, option.count]))
            const options: FacetOption[] = (facet.fixedOptions ?? []).map((option) => ({
                ...option,
                count: countByValue.get(option.value) ?? 0,
            }))
            return (
                <Facet
                    key={facet.key}
                    title={facet.title}
                    options={options}
                    selected={selected}
                    onToggle={onToggle}
                    loading={loadingByField[facet.facetField]}
                    collapsed={collapsed}
                    onToggleCollapsed={onToggleCollapsed}
                    dimZeroCounts
                />
            )
        }

        // Dynamic facet: values + counts come straight from the cross-filtered endpoint (zeros never appear).
        return (
            <Facet
                key={facet.key}
                title={facet.title}
                options={fetched}
                selected={selected}
                onToggle={onToggle}
                loading={loadingByField[facet.facetField]}
                emptyLabel={facet.emptyLabel}
                searchValue={facet.searchable ? (facetSearch[facet.facetField] ?? '') : undefined}
                onSearchChange={facet.searchable ? (value) => setFacetSearch(facet.facetField, value) : undefined}
                searchPlaceholder={facet.searchPlaceholder}
                collapsed={collapsed}
                onToggleCollapsed={onToggleCollapsed}
                maxHeight={facet.maxHeight}
            />
        )
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
