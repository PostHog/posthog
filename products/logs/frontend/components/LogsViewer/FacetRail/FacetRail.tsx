import { useActions, useValues } from 'kea'
import { useCallback, useMemo, useRef } from 'react'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'

import { logsViewerConfigLogic } from 'products/logs/frontend/components/LogsViewer/config/logsViewerConfigLogic'

const DEFAULT_WIDTH_PX = 240
const COLLAPSE_THRESHOLD_PX = 120

export interface FacetRailProps {
    id: string
}

/** Resizable left-hand facet rail. Shell only — facets and filtering land in follow-up work. */
export function FacetRail({ id }: FacetRailProps): JSX.Element {
    const railRef = useRef<HTMLDivElement>(null)
    const { setFacetRailCollapsed } = useActions(logsViewerConfigLogic)

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
                <p className="text-xs text-muted m-0">Facets will appear here.</p>
            </div>
            <Resizer {...resizerLogicProps} visible={false} offset="0.25rem" handleClassName="rounded my-1" />
        </div>
    )
}
