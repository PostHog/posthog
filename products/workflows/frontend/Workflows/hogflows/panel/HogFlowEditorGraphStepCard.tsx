import { NodeToolbar, Position, useStore } from '@xyflow/react'
import { useValues } from 'kea'

import { HOG_FLOW_STEP_CARD_OFFSET, HOG_FLOW_STEP_CARD_WIDTH, hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { NODE_HEIGHT } from '../react_flow_utils/constants'
import { HogFlowEditorPanelStep } from './HogFlowEditorPanelStep'

const CARD_EDGE_PADDING = 16
const CARD_MIN_HEIGHT = 240

export function HogFlowEditorGraphStepCard(): JSX.Element | null {
    const { selectedNode } = useValues(hogFlowEditorLogic)
    const [, translateY, zoom] = useStore((state) => state.transform)
    const paneWidth = useStore((state) => state.width)
    const paneHeight = useStore((state) => state.height)

    if (!selectedNode) {
        return null
    }

    const stepTop = selectedNode.position.y * zoom + translateY
    const maxHeight = Math.max(CARD_MIN_HEIGHT, paneHeight - Math.max(stepTop, 0) - CARD_EDGE_PADDING)
    const width = Math.min(HOG_FLOW_STEP_CARD_WIDTH, paneWidth - CARD_EDGE_PADDING * 2)

    return (
        <NodeToolbar
            nodeId={selectedNode.id}
            isVisible
            position={Position.Right}
            align="start"
            offset={HOG_FLOW_STEP_CARD_OFFSET}
            // Stop wheel, drag and pan from reaching the canvas so the card scrolls like a normal panel.
            className="nowheel nodrag nopan"
        >
            <div className="relative" style={{ width }}>
                <div
                    aria-hidden="true"
                    className="absolute h-px bg-border-bold"
                    style={{
                        left: -HOG_FLOW_STEP_CARD_OFFSET,
                        width: HOG_FLOW_STEP_CARD_OFFSET,
                        top: (NODE_HEIGHT * zoom) / 2,
                    }}
                />
                <HogFlowEditorPanelStep className="shadow-[0_3px_0_var(--border)]" style={{ maxHeight }} />
            </div>
        </NodeToolbar>
    )
}
