import { ADVENT_FLOW_PHONE_WIDTH, AdventFlowLayout, AdventFlowOrientation } from './adventFlowLayout'

const COLUMN_BELOW = 560

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
        const zoom = stage.width / ADVENT_FLOW_PHONE_WIDTH
        return {
            zoom,
            box: { left: 0, top: 0 },
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
