import './AdventFlowStage.scss'

import { memo } from 'react'

import { cn } from 'lib/utils/css-classes'

import { arrowHead, EDGE_LABEL_HEIGHT, roundedPath } from '../../Workflows/hogflows/editor/tile-canvas/tileCanvasLayout'
import { AdventFlowEdge, AdventFlowLayout } from './adventFlowLayout'

export interface AdventFlowEdgesProps {
    layout: AdventFlowLayout
    isEdgeEmphasized: (edge: AdventFlowEdge) => boolean
}

const PILL_CLEARANCE = 10

// A centred pill may use the run on both sides of its centre, so it never reaches the arrow into the next door.
// On a vertical run, the pill sits beside its lane and needs no cap.
function pillWidthOf(edge: AdventFlowEdge): number | undefined {
    const [from, to] = edge.points.slice(-2)
    if (!edge.labelAt || from.y !== to.y) {
        return undefined
    }
    return 2 * (Math.abs(to.x - edge.labelAt.x) - PILL_CLEARANCE)
}

export const AdventFlowEdges = memo(function AdventFlowEdges({
    layout,
    isEdgeEmphasized,
}: AdventFlowEdgesProps): JSX.Element {
    const lockedIds = new Set(layout.nodes.filter((node) => node.door?.lockReason === 'date').map((node) => node.id))
    const isFuture = (edge: AdventFlowEdge): boolean => !edge.walked && lockedIds.has(edge.target)
    return (
        <>
            <svg
                className="AdventFlowEdges pointer-events-none absolute left-0 top-0 overflow-visible"
                width={layout.width}
                height={layout.height}
                aria-hidden
            >
                {layout.edges.map((edge) => (
                    <g
                        key={edge.id}
                        data-edge={edge.id}
                        data-emphasized={isEdgeEmphasized(edge)}
                        className={cn(
                            'AdventFlowEdges__edge',
                            edge.walked && 'AdventFlowEdges__edge--walked',
                            isFuture(edge) && 'AdventFlowEdges__edge--future'
                        )}
                    >
                        <path d={roundedPath(edge.points)} />
                        <path d={arrowHead(edge.points)} />
                    </g>
                ))}
            </svg>
            {layout.edges.map(
                (edge) =>
                    edge.label &&
                    edge.labelAt && (
                        <span
                            key={edge.id}
                            className={cn(
                                'AdventFlowEdges__pill pointer-events-none absolute flex flex-wrap items-center justify-center gap-x-1 border bg-surface-primary px-2 text-center font-semibold',
                                isFuture(edge) && 'AdventFlowEdges__pill--future'
                            )}
                            style={{
                                left: edge.labelAt.x,
                                top: edge.labelAt.y,
                                minHeight: EDGE_LABEL_HEIGHT,
                                maxWidth: pillWidthOf(edge),
                            }}
                        >
                            {edge.label}
                            {edge.share !== null && <span className="font-normal text-secondary">{edge.share}%</span>}
                        </span>
                    )
            )}
        </>
    )
})
