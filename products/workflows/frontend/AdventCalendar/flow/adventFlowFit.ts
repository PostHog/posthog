import { ADVENT_FLOW_PHONE_WIDTH, AdventFlowLayout, AdventFlowOrientation } from './adventFlowLayout'

// Below this width the rows would zoom out past 0.8, which shrinks the 12 px captions to under 10 px.
const COLUMN_BELOW = 960
const MAX_COLUMN_ZOOM = 1.25

export interface AdventFlowFit {
    zoom: number
    box: { left: number; top: number }
    content: { width: number; height: number }
}

export function adventFlowOrientation(stage: { width: number }): AdventFlowOrientation {
    return stage.width < COLUMN_BELOW ? 'column' : 'rows'
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
