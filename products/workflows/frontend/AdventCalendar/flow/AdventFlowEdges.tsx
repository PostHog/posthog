import './AdventFlowStage.scss'

import { cn } from 'lib/utils/css-classes'

import { arrowHead, EDGE_LABEL_HEIGHT, roundedPath } from '../../Workflows/hogflows/editor/tile-canvas/tileCanvasLayout'
import { AdventFlowEdge, AdventFlowLayout } from './adventFlowLayout'

export interface AdventFlowEdgesProps {
    layout: AdventFlowLayout
    isEdgeEmphasized: (edge: AdventFlowEdge) => boolean
}

export function AdventFlowEdges({ layout, isEdgeEmphasized }: AdventFlowEdgesProps): JSX.Element {
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
                                'AdventFlowEdges__pill pointer-events-none absolute flex items-center gap-1 whitespace-nowrap rounded-full border bg-surface-primary px-2 text-[11px] font-semibold',
                                isFuture(edge) && 'AdventFlowEdges__pill--future'
                            )}
                            style={{ left: edge.labelAt.x, top: edge.labelAt.y, height: EDGE_LABEL_HEIGHT }}
                        >
                            {edge.label}
                            {edge.share !== null && <span className="font-normal text-secondary">{edge.share}%</span>}
                        </span>
                    )
            )}
        </>
    )
}
