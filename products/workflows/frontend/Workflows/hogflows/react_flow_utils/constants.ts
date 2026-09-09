export const NODE_WIDTH = 120
export const NODE_HEIGHT = 34

export const NODE_NODE_GAP = 100

// Minimum horizontal distance between parallel edges
export const MINIMUM_EDGE_SPACING = 170

// NODE_EDGE_GAP is MINIMUM_EDGE_SPACING - 1 to account for the 1px stroke width of edges
export const NODE_EDGE_GAP = MINIMUM_EDGE_SPACING - 1
export const NODE_LAYER_GAP = 75

// React Flow defaults to a 0.5 floor, which isn't enough to fit a wide branching workflow on screen.
// This also raises the ceiling on the initial fitView, which is bounded by the instance's minZoom.
export const MIN_ZOOM = 0.1

// Below this, a node's description renders as an illegible smudge (it's 0.3rem at zoom 1), so we drop
// it and leave the node as a labelled block for reading the overall shape of the workflow.
export const LOW_DETAIL_ZOOM = 0.4

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
