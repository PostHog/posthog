import { useActions, useValues } from 'kea'
import { useCallback, useMemo, useRef } from 'react'

import { LemonInput } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'

import { logsViewerConfigLogic } from 'products/logs/frontend/components/LogsViewer/config/logsViewerConfigLogic'
import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'

import { Facet, FacetOption } from './Facet'
import { facetCountsLogic } from './facetCountsLogic'
import { facetRailLogic } from './facetRailLogic'
import {
    FacetConfig,
    FacetFilterKey,
    facetsByGroup,
    filterFacetsByName,
    mergeSelectedIntoOptions,
    resourceAttributeValues,
} from './facets'

const DEFAULT_WIDTH_PX = 240
const COLLAPSE_THRESHOLD_PX = 120

export interface FacetRailProps {
    id: string
}

/** Resizable left-hand facet rail, rendered entirely from the FACETS config (see facets.ts). */
export function FacetRail({ id }: FacetRailProps): JSX.Element {
    const railRef = useRef<HTMLDivElement>(null)
    const { setFacetRailCollapsed } = useActions(logsViewerConfigLogic)
    const { severityLevels, serviceNames, filterGroup } = useValues(logsViewerFiltersLogic)
    const { facetValues, loadingFacetKeys, facetSearch, visibleFacets } = useValues(facetCountsLogic({ id }))
    const { setFacetSearch } = useActions(facetCountsLogic({ id }))
    const { collapsedFacets, facetNameSearch } = useValues(facetRailLogic({ id }))
    const { toggleFacetValue, toggleFacetCollapsed, setFacetNameSearch } = useActions(facetRailLogic({ id }))

    const selectedByKey: Record<FacetFilterKey, string[]> = {
        severityLevels: severityLevels ?? [],
        serviceNames: serviceNames ?? [],
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
        const { source } = facet
        // Selection: column facets read their dedicated filter field; resource-attribute facets read
        // their log_resource_attribute filter out of the group.
        const selected =
            source.type === 'resourceAttribute'
                ? resourceAttributeValues(filterGroup, source.key)
                : selectedByKey[source.filterKey]
        // Values + counts come from the cross-filtered endpoint, keyed by facet.key.
        const fetched: FacetOption[] = (facetValues[facet.key] ?? []).map((r) => ({
            value: r.value,
            label: r.value,
            count: r.count,
        }))
        const loading = loadingFacetKeys.includes(facet.key)
        const onToggle = (value: string): void => toggleFacetValue(source, value)
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
                    loading={loading}
                    collapsed={collapsed}
                    onToggleCollapsed={onToggleCollapsed}
                    dimZeroCounts
                />
            )
        }

        // Dynamic facet: values + counts come from the cross-filtered endpoint, plus any selected
        // values it didn't return (zero matches in scope, or below the top-N cutoff) so an active
        // filter — e.g. from an old saved-view URL — is always visible and removable.
        return (
            <Facet
                key={facet.key}
                title={facet.title}
                options={mergeSelectedIntoOptions(
                    fetched,
                    selected,
                    facet.searchable ? facetSearch[facet.key] : undefined
                )}
                selected={selected}
                onToggle={onToggle}
                loading={loading}
                emptyLabel={facet.emptyLabel}
                searchValue={facet.searchable ? (facetSearch[facet.key] ?? '') : undefined}
                onSearchChange={facet.searchable ? (value) => setFacetSearch(facet.key, value) : undefined}
                searchPlaceholder={facet.searchPlaceholder}
                collapsed={collapsed}
                onToggleCollapsed={onToggleCollapsed}
                maxHeight={facet.maxHeight}
            />
        )
    }

    // Filter the rail by the field-name search, then group — empty groups fall away in facetsByGroup.
    const displayedGroups = facetsByGroup(filterFacetsByName(visibleFacets, facetNameSearch))

    return (
        <div
            ref={railRef}
            className="relative flex flex-col shrink-0 border rounded bg-surface-primary overflow-hidden"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width: desiredSize ?? DEFAULT_WIDTH_PX, minWidth: 'min-content', maxWidth: '40%' }}
            data-attr="logs-facet-rail"
        >
            <div className="px-2 py-1 border-b">
                <LemonInput
                    type="search"
                    size="small"
                    fullWidth
                    placeholder="Search facets…"
                    value={facetNameSearch}
                    onChange={setFacetNameSearch}
                    data-attr="logs-facet-rail-search"
                />
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto p-2">
                {displayedGroups.length === 0 && facetNameSearch.trim() ? (
                    <div className="px-1 text-xs text-muted">No matching facets</div>
                ) : (
                    displayedGroups.map(([group, facets]) => (
                        <div key={group}>
                            <div className="px-1 pb-1 mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted border-b border-primary">
                                {group}
                            </div>
                            {facets.map(renderFacet)}
                        </div>
                    ))
                )}
            </div>
            <Resizer {...resizerLogicProps} visible={false} offset="0.25rem" handleClassName="rounded my-1" />
        </div>
    )
}
