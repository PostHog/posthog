import { EDGE_LABEL_HEIGHT, edgeLabelWidth, shortLabel } from './tileCanvasLayout'
import type { Point } from './tileCanvasModel'

export function TileEdgeLabel({ label, at }: { label: string; at: Point }): JSX.Element {
    return (
        <div
            className="nodrag nopan absolute flex items-center justify-center whitespace-nowrap rounded-full border bg-surface-primary px-2 text-xs font-semibold"
            style={{
                transform: `translate(-50%, -50%) translate(${at.x}px, ${at.y}px)`,
                height: EDGE_LABEL_HEIGHT,
                minWidth: edgeLabelWidth(label),
                pointerEvents: 'all',
            }}
            title={label === shortLabel(label) ? undefined : label}
        >
            {shortLabel(label)}
        </div>
    )
}
