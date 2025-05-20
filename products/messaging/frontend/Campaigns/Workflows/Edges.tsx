import { IconPlus } from '@posthog/icons'
import { BaseEdge, EdgeLabelRenderer, type EdgeProps, getBezierPath } from '@xyflow/react'

export default function AddEdge({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    markerEnd,
}: EdgeProps): JSX.Element {
    const [edgePath] = getBezierPath({
        sourceX,
        sourceY,
        sourcePosition,
        targetX,
        targetY,
        targetPosition,
    })

    return (
        <>
            <BaseEdge path={edgePath} markerEnd={markerEnd} />
            <EdgeLabelRenderer>
                <div className="button-edge__label nodrag nopan">
                    <IconPlus />
                </div>
            </EdgeLabelRenderer>
        </>
    )
}
