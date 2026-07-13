import { useActions, useValues } from 'kea'
import { useCallback, useMemo, useRef } from 'react'

import { LemonInput } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'

import { tracingConfigLogic } from '../../tracingConfigLogic'
import { tracingFiltersLogic } from '../../tracingFiltersLogic'
import { Facet } from './Facet'
import { facetCountsLogic } from './facetCountsLogic'
import { facetRailLogic } from './facetRailLogic'
import {
    FacetConfig,
    FacetOption,
    facetSelectedValues,
    facetsByGroup,
    filterFacetsByName,
    mergeSelectedIntoOptions,
} from './facets'

const DEFAULT_WIDTH_PX = 240
const COLLAPSE_THRESHOLD_PX = 120

/** Resizable left-hand facet rail, rendered entirely from the FACETS config (see facets.ts). */
export function FacetRail(): JSX.Element {
    const railRef = useRef<HTMLDivElement>(null)
    const { setFacetRailCollapsed } = useActions(tracingConfigLogic)
    const { serviceNames, filters } = useValues(tracingFiltersLogic)
    const { facetValues, facetValuesLoading, visibleFacets } = useValues(facetCountsLogic)
    const { collapsedFacets, facetNameSearch } = useValues(facetRailLogic)
    const { toggleFacetValue, toggleFacetCollapsed, setFacetNameSearch } = useActions(facetRailLogic)

    const onToggleClosed = useCallback(
        (shouldBeClosed: boolean) => setFacetRailCollapsed(shouldBeClosed),
        [setFacetRailCollapsed]
    )
    const resizerLogicProps: ResizerLogicProps = useMemo(
        () => ({
            logicKey: 'tracing-facet-rail',
            containerRef: railRef,
            persistent: true,
            persistPrefix: '2026-07-06',
            placement: 'right',
            closeThreshold: COLLAPSE_THRESHOLD_PX,
            onToggleClosed,
        }),
        [onToggleClosed]
    )
    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    const renderFacet = (facet: FacetConfig): JSX.Element => {
        const { source } = facet
        // Selection: the service facet reads the dedicated serviceNames field; everything else reads
        // its property filter out of the group (see facetSelectedValues).
        const selected = facetSelectedValues(filters.filterGroup, serviceNames, source)
        // Values + counts come from the cross-filtered endpoint, keyed by facet.key.
        const fetched: FacetOption[] = (facetValues[facet.key] ?? []).map((row) => ({
            value: row.value,
            label: row.value,
            count: row.count,
        }))
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
                    loading={facetValuesLoading}
                    collapsed={collapsed}
                    onToggleCollapsed={onToggleCollapsed}
                    dimZeroCounts
                />
            )
        }

        // Dynamic facet: values + counts come straight from the cross-filtered endpoint (zeros never
        // appear), with any selected-but-absent values injected so they stay visible and toggleable.
        return (
            <Facet
                key={facet.key}
                title={facet.title}
                options={mergeSelectedIntoOptions(fetched, selected)}
                selected={selected}
                onToggle={onToggle}
                loading={facetValuesLoading}
                emptyLabel={facet.emptyLabel}
                collapsed={collapsed}
                onToggleCollapsed={onToggleCollapsed}
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
            data-attr="tracing-facet-rail"
        >
            <div className="px-2 py-1 border-b">
                <LemonInput
                    type="search"
                    size="small"
                    fullWidth
                    placeholder="Search facets…"
                    value={facetNameSearch}
                    onChange={setFacetNameSearch}
                    data-attr="tracing-facet-rail-search"
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
