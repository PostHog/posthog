import { HogFlowEdge } from '../types'
import { MINIMUM_EDGE_SPACING } from './constants'
import { getEdgeHorizontalOffsets, getPointAtYValue, getSmartStepPath } from './SmartEdge'

describe('SmartEdge geometry', () => {
    test.each([
        { name: 'straight vertical edge', horizontalOffset: 0, targetX: 0, expectedX: 0 },
        { name: 'edge that branches right, then goes down', horizontalOffset: 170, targetX: 170, expectedX: 170 },
        {
            name: 'edge that branches left, travels down, then goes back in',
            horizontalOffset: -170,
            targetX: 0,
            expectedX: -170,
        },
        {
            name: 'edge that goes down, then moves in to a target on the right',
            horizontalOffset: 0,
            targetX: 300,
            expectedX: 0,
        },
    ])('puts the label on the vertical part of a $name', ({ horizontalOffset, targetX, expectedX }) => {
        const [path] = getSmartStepPath({ sourceX: 0, sourceY: 0, targetX, targetY: 200, horizontalOffset })

        expect(getPointAtYValue(path, 20)).toEqual({ x: expectedX, y: 20 })
    })

    it('spreads edges from one source with branches in index order and continue last', () => {
        const edges: HogFlowEdge[] = [
            { from: 'cond', to: 'exit', type: 'continue' },
            { from: 'cond', to: 'b', type: 'branch', index: 1 },
            { from: 'cond', to: 'a', type: 'branch', index: 0 },
            { from: 'a', to: 'exit', type: 'continue' },
        ]

        const offsets = getEdgeHorizontalOffsets(edges, (edge) => `${edge.from}->${edge.to}`)

        expect(Object.fromEntries(offsets)).toEqual({
            'cond->a': -MINIMUM_EDGE_SPACING,
            'cond->b': 0,
            'cond->exit': MINIMUM_EDGE_SPACING,
            'a->exit': 0,
        })
    })
})
