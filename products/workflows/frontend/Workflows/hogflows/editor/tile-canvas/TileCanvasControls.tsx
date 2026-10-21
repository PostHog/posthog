import { ControlButton, Controls, useReactFlow, useStore } from '@xyflow/react'

import { IconExpand45, IconMinus, IconPlus } from '@posthog/icons'

/** React Flow's own buttons take no data attributes, so the canvas draws its own to keep their use measurable. */
export function TileCanvasControls(): JSX.Element {
    const { zoomIn, zoomOut, fitView } = useReactFlow()
    const atMin = useStore((state) => state.transform[2] <= state.minZoom)
    const atMax = useStore((state) => state.transform[2] >= state.maxZoom)
    return (
        <Controls showZoom={false} showFitView={false} showInteractive={false}>
            <ControlButton
                onClick={() => void zoomIn()}
                disabled={atMax}
                title="Zoom in"
                aria-label="Zoom in"
                data-attr="workflow-tile-zoom-in"
            >
                <IconPlus />
            </ControlButton>
            <ControlButton
                onClick={() => void zoomOut()}
                disabled={atMin}
                title="Zoom out"
                aria-label="Zoom out"
                data-attr="workflow-tile-zoom-out"
            >
                <IconMinus />
            </ControlButton>
            <ControlButton
                onClick={() => void fitView()}
                title="Fit view"
                aria-label="Fit view"
                data-attr="workflow-tile-fit-view"
            >
                <IconExpand45 />
            </ControlButton>
        </Controls>
    )
}
