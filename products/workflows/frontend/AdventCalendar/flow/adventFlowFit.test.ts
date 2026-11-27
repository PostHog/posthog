import { drawAdventRewards } from '../adventDraw'
import { buildAdventGraph } from '../adventGraph'
import { adventFlowFit, adventFlowOrientation } from './adventFlowFit'
import { ADVENT_FLOW_DOOR, adventFlowLayout } from './adventFlowLayout'

const GRAPH = buildAdventGraph(
    { opened: [], answers: {} },
    1,
    drawAdventRewards('0190d8a2-1c4e-7b3a-9f21-5a6b7c8d9e01')
)

describe('adventFlowFit', () => {
    it.each([
        ['a small phone', 360, 740, 'column', 65],
        ['a phone', 390, 844, 'column', 70],
        ['a tablet in portrait', 740, 900, 'column', 88],
        ['a narrow desktop stage', 950, 700, 'column', 88],
        ['the narrowest desktop stage with rows', 960, 800, 'rows', 56],
        ['a laptop', 1024, 768, 'rows', 60],
        ['a wide desktop', 1440, 900, 'rows', 76],
    ])('fits the doors on %s (%s × %s) into %s at %s px', (_, width, height, orientation, doorSize) => {
        const stage = { width, height }
        const layout = adventFlowLayout(GRAPH, {}, adventFlowOrientation(stage))
        const { zoom, box } = adventFlowFit(stage, layout)

        expect({
            orientation: layout.orientation,
            doorSize: Math.round(ADVENT_FLOW_DOOR.width * zoom),
            centred: Math.round(2 * box.left + layout.width * zoom) === width,
        }).toEqual({ orientation, doorSize, centred: true })
    })
})
