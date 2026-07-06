import { useActions, useValues } from 'kea'
import { useCallback, useMemo, useRef } from 'react'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'

import { tracingConfigLogic } from '../../tracingConfigLogic'

const DEFAULT_WIDTH_PX = 240
const COLLAPSE_THRESHOLD_PX = 120

/**
 * Resizable left-hand facet rail for the tracing scene. Facets (values + counts) land in
 * follow-up PRs — this is the flag-gated shell: sizing, persistence, and collapse behavior.
 */
export function FacetRail(): JSX.Element {
    const railRef = useRef<HTMLDivElement>(null)
    const { setFacetRailCollapsed } = useActions(tracingConfigLogic)

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

    return (
        <div
            ref={railRef}
            className="relative flex flex-col shrink-0 border rounded bg-surface-primary overflow-hidden"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width: desiredSize ?? DEFAULT_WIDTH_PX, minWidth: 'min-content', maxWidth: '40%' }}
            data-attr="tracing-facet-rail"
        >
            <div className="flex-1 min-h-0 overflow-y-auto p-2">
                <div className="px-1 text-xs text-muted">Facets will appear here.</div>
            </div>
            <Resizer {...resizerLogicProps} visible={false} offset="0.25rem" handleClassName="rounded my-1" />
        </div>
    )
}
