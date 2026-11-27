import {
    ADVENT_FLOW_PHONE_WIDTH,
    ADVENT_FLOW_ROWS_SIZE,
    AdventFlowLayout,
    AdventFlowOrientation,
} from './adventFlowLayout'

// Rows zoomed out past 0.8 shrink the 12 px captions to under 10 px, on a narrow stage or on a short one.
const MIN_ROWS_ZOOM = 0.8
const MAX_COLUMN_ZOOM = 1.25

export interface AdventFlowFit {
    zoom: number
    box: { left: number; top: number }
    content: { width: number; height: number }
}

export function adventFlowOrientation(stage: { width: number; height: number }): AdventFlowOrientation {
    const zoom = Math.min(stage.width / ADVENT_FLOW_ROWS_SIZE.width, stage.height / ADVENT_FLOW_ROWS_SIZE.height)
    return zoom < MIN_ROWS_ZOOM ? 'column' : 'rows'
}

export function adventFlowFit(stage: { width: number; height: number }, layout: AdventFlowLayout): AdventFlowFit {
    if (layout.orientation === 'column') {
        const zoom = Math.min(stage.width / ADVENT_FLOW_PHONE_WIDTH, MAX_COLUMN_ZOOM)
        return {
            zoom,
            box: { left: (stage.width - ADVENT_FLOW_PHONE_WIDTH * zoom) / 2, top: 0 },
            content: { width: stage.width, height: Math.max(stage.height, layout.height * zoom) },
        }
    }
    const zoom = Math.min(stage.width / layout.width, stage.height / layout.height)
    return {
        zoom,
        box: { left: (stage.width - layout.width * zoom) / 2, top: (stage.height - layout.height * zoom) / 2 },
        content: stage,
    }
}
