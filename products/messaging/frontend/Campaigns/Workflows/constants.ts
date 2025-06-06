import { MarkerType } from '@xyflow/react'

export const DEFAULT_NODE_OPTIONS = {
    deletable: true,
    draggable: false,
    selectable: true,
    connectable: false,
}

export const DEFAULT_EDGE_OPTIONS = {
    type: 'smoothstep',
    deletable: false,
    draggable: false,
    reconnectable: false,
    selectable: false,
    focusable: false,
    markerEnd: {
        type: MarkerType.ArrowClosed,
    },
    labelShowBg: false,
}

// Keep in sync with Nodes.tsx -> BaseNode styling
export const NODE_WIDTH = 100
export const NODE_HEIGHT = 34

export const NODE_GAP = 100

export const TOP_HANDLE_POSITION = {
    x: NODE_WIDTH / 2,
    y: 0,
}

export const BOTTOM_HANDLE_POSITION = {
    x: NODE_WIDTH / 2,
    y: NODE_HEIGHT,
}

export const LEFT_HANDLE_POSITION = {
    x: 0,
    y: NODE_HEIGHT / 2,
}

export const RIGHT_HANDLE_POSITION = {
    x: NODE_WIDTH,
    y: NODE_HEIGHT / 2,
}
