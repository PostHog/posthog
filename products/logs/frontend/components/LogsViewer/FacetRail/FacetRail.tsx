import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useMemo, useRef } from 'react'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'

import { LogSeverityLevel } from '~/queries/schema/schema-general'

import { logsViewerConfigLogic } from 'products/logs/frontend/components/LogsViewer/config/logsViewerConfigLogic'
import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'
import { serviceFilterLogic } from 'products/logs/frontend/components/LogsViewer/Filters/serviceFilterLogic'
import { SEVERITY_BAR_COLORS } from 'products/logs/frontend/components/VirtualizedLogsList/columnDefinitions'

import { Facet, FacetOption } from './Facet'
import { facetRailLogic } from './facetRailLogic'

const DEFAULT_WIDTH_PX = 240
const COLLAPSE_THRESHOLD_PX = 120

// Colors mirror the severity bar in the log rows (SEVERITY_BAR_COLORS) so the rail matches the viewer.
const SEVERITY_OPTIONS: FacetOption[] = (
    [
        ['trace', 'Trace'],
        ['debug', 'Debug'],
        ['info', 'Info'],
        ['warn', 'Warn'],
        ['error', 'Error'],
        ['fatal', 'Fatal'],
    ] as const
).map(([value, label]) => ({ value, label, color: SEVERITY_BAR_COLORS[value] }))

export interface FacetRailProps {
    id: string
}

/** Resizable left-hand facet rail. Level + Service today; more facets and counts land in follow-up work. */
export function FacetRail({ id }: FacetRailProps): JSX.Element {
    const railRef = useRef<HTMLDivElement>(null)
    const { setFacetRailCollapsed } = useActions(logsViewerConfigLogic)
    const { severityLevels, serviceNames, utcDateRange } = useValues(logsViewerFiltersLogic)
    const { collapsedFacets } = useValues(facetRailLogic({ id }))
    const { toggleSeverityLevel, toggleServiceName, toggleFacetCollapsed } = useActions(facetRailLogic({ id }))

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
                <div className="px-1 pb-1 mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted border-b border-primary">
                    Standard
                </div>
                <Facet
                    title="Level"
                    options={SEVERITY_OPTIONS}
                    selected={severityLevels ?? []}
                    onToggle={(value) => toggleSeverityLevel(value as LogSeverityLevel)}
                    collapsed={collapsedFacets.includes('level')}
                    onToggleCollapsed={() => toggleFacetCollapsed('level')}
                />
                <BindLogic logic={serviceFilterLogic} props={{ dateRange: utcDateRange }}>
                    <ServiceFacet
                        selected={serviceNames ?? []}
                        onToggle={toggleServiceName}
                        collapsed={collapsedFacets.includes('service')}
                        onToggleCollapsed={() => toggleFacetCollapsed('service')}
                    />
                </BindLogic>
            </div>
            <Resizer {...resizerLogicProps} visible={false} offset="0.25rem" handleClassName="rounded my-1" />
        </div>
    )
}

function ServiceFacet({
    selected,
    onToggle,
    collapsed,
    onToggleCollapsed,
}: {
    selected: string[]
    onToggle: (name: string) => void
    collapsed: boolean
    onToggleCollapsed: () => void
}): JSX.Element {
    const { serviceNames, allServiceNamesLoading, search } = useValues(serviceFilterLogic)
    const { setSearch } = useActions(serviceFilterLogic)

    const options: FacetOption[] = serviceNames.map((name) => ({ value: name, label: name }))

    return (
        <Facet
            title="Service"
            options={options}
            selected={selected}
            onToggle={onToggle}
            loading={allServiceNamesLoading}
            emptyLabel="No services"
            searchValue={search}
            onSearchChange={setSearch}
            searchPlaceholder="Search services…"
            collapsed={collapsed}
            onToggleCollapsed={onToggleCollapsed}
            maxHeight={300}
        />
    )
}
