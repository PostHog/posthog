import { EdgeLabelRenderer, EdgeProps } from '@xyflow/react'
import { useState } from 'react'

import { QuickAddButton } from './QuickAddButton'
import { arrowHead, EDGE_LABEL_HEIGHT, edgeLabelWidth, insertPoint, roundedPath, shortLabel } from './tileCanvasLayout'
import type { TileEdgeType } from './tileCanvasNodes'

const QUICK_ADD_GAP = 14

export function TileEdge({ data }: EdgeProps<TileEdgeType>): JSX.Element | null {
    const routed = data?.routed
    const [hovered, setHovered] = useState(false)
    if (!data || !routed) {
        return null
    }
    const { edge } = data
    const label = edge.label && routed.label ? edge.label : undefined
    const at = label && routed.label ? routed.label : insertPoint(routed.points)
    return (
        <>
            <path d={roundedPath(routed.points)} fill="none" stroke="var(--tile-canvas-edge)" strokeWidth={1.5} />
            <path d={arrowHead(routed.points)} fill="none" stroke="var(--tile-canvas-edge)" strokeWidth={1.5} />
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
                        at={{ x: at.x + (label ? edgeLabelWidth(label) / 2 + QUICK_ADD_GAP : 0), y: at.y }}
                    />
                )}
            </EdgeLabelRenderer>
        </>
    )
}
