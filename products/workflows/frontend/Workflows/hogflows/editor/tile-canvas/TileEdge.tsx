import { EdgeLabelRenderer, EdgeProps } from '@xyflow/react'
import { useValues } from 'kea'
import { useState } from 'react'

import { getEdgeId } from '../../edgeId'
import { QuickAddButton } from './QuickAddButton'
import {
    arrowHead,
    EDGE_LABEL_HEIGHT,
    edgeLabelWidth,
    quickAddPoint,
    roundedPath,
    shortLabel,
} from './tileCanvasLayout'
import { tileCanvasLogic } from './tileCanvasLogic'
import { edgeLabelText, type TileEdgeType } from './tileCanvasNodes'

export function TileEdge({ data }: EdgeProps<TileEdgeType>): JSX.Element | null {
    const routed = data?.routed
    const [hovered, setHovered] = useState(false)
    const { dropTargetEdgeKey } = useValues(tileCanvasLogic)
    if (!data || !routed) {
        return null
    }
    const { edge } = data
    const label = edgeLabelText(edge, routed)
    const isDropTarget = !!edge.insertEdge && dropTargetEdgeKey === getEdgeId(edge.insertEdge)
    const stroke = isDropTarget ? 'var(--color-accent)' : 'var(--tile-canvas-edge)'
    return (
        <>
            <path
                d={roundedPath(routed.points)}
                className="TileCanvas__edge"
                fill="none"
                stroke={stroke}
                strokeWidth={isDropTarget ? 2 : 1.5}
            />
            <path
                d={arrowHead(routed.points)}
                className="TileCanvas__edge"
                fill="none"
                stroke={stroke}
                strokeWidth={isDropTarget ? 2 : 1.5}
            />
            {/* A wide invisible stroke lets the pointer find the arrow, which shows the button that adds a step on it. */}
            <path
                d={roundedPath(routed.points)}
                fill="none"
                stroke="transparent"
                strokeWidth={24}
                style={{ pointerEvents: 'stroke' }}
                onMouseEnter={() => setHovered(true)}
                onMouseLeave={() => setHovered(false)}
            />
            <EdgeLabelRenderer>
                {label && routed.label && (
                    <div
                        className="nodrag nopan absolute flex items-center justify-center whitespace-nowrap rounded-full border bg-surface-primary px-2 text-xs font-semibold"
                        style={{
                            transform: `translate(-50%, -50%) translate(${routed.label.x}px, ${routed.label.y}px)`,
                            height: EDGE_LABEL_HEIGHT,
                            minWidth: edgeLabelWidth(label),
                            pointerEvents: 'all',
                        }}
                        title={label === shortLabel(label) ? undefined : label}
                    >
                        {shortLabel(label)}
                    </div>
                )}
                {edge.insertEdge && (
                    <QuickAddButton
                        edge={edge.insertEdge}
                        revealed={hovered}
                        isDropTarget={isDropTarget}
                        at={quickAddPoint(routed, label)}
                    />
                )}
            </EdgeLabelRenderer>
        </>
    )
}
