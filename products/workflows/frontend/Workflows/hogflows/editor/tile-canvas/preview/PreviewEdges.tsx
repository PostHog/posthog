import { arrowHead, type CanvasLayout, roundedPath } from '../tileCanvasLayout'
import type { Point, VisibleEdge } from '../tileCanvasModel'
import { edgeLabelText } from '../tileCanvasNodes'
import { TileEdgeLabel } from '../TileEdgeLabel'

export function PreviewEdges({
    edges,
    layout,
    shift,
}: {
    edges: VisibleEdge[]
    layout: CanvasLayout
    shift: Point
}): JSX.Element {
    const routed = edges.flatMap((edge) => {
        const route = layout.edges[edge.id]
        if (!route) {
            return []
        }
        const points = route.points.map((point) => ({ x: point.x + shift.x, y: point.y + shift.y }))
        const label = edgeLabelText(edge, route)
        const labelAt = route.label && { x: route.label.x + shift.x, y: route.label.y + shift.y }
        return [{ id: edge.id, points, label, labelAt }]
    })
    return (
        <div className="WorkflowCanvasPreview__edges pointer-events-none absolute inset-0">
            <svg className="absolute inset-0 size-full overflow-visible" aria-hidden>
                {routed.map(({ id, points }) => (
                    <g key={id} fill="none" stroke="var(--tile-canvas-edge)" strokeWidth={1.5}>
                        <path d={roundedPath(points)} />
                        <path d={arrowHead(points)} />
                    </g>
                ))}
            </svg>
            {routed.map(
                ({ id, label, labelAt }) => label && labelAt && <TileEdgeLabel key={id} label={label} at={labelAt} />
            )}
        </div>
    )
}
