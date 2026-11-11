import type { ReservedRegion } from 'react-native-reserved-regions'

import { displayPanes, overlayPane } from './displayRegions'

const BOUNDS = { x: 0, y: 0, width: 867, height: 669 }

describe('display regions', () => {
    test.each([
        {
            frame: { x: 465, y: 0, width: 16, height: 669 },
            expected: [
                { x: 0, y: 0, width: 465, height: 669 },
                { x: 481, y: 0, width: 386, height: 669 },
            ],
        },
        {
            frame: { x: 465, y: 0, width: 0, height: 669 },
            expected: [
                { x: 0, y: 0, width: 465, height: 669 },
                { x: 465, y: 0, width: 402, height: 669 },
            ],
        },
        {
            frame: { x: 0, y: 320, width: 867, height: 16 },
            expected: [
                { x: 0, y: 0, width: 867, height: 320 },
                { x: 0, y: 336, width: 867, height: 333 },
            ],
        },
        { frame: { x: 950, y: 0, width: 16, height: 669 }, expected: [BOUNDS] },
    ])('keeps content on each side of the active fold ($frame)', ({ frame, expected }) => {
        expect(displayPanes(BOUNDS, [{ kind: 'division', frame, occludesContent: false }])).toEqual(expected)
    })

    test.each([
        { anchor: undefined, x: 481 },
        { anchor: { x: 20, y: 40, width: 200, height: 60 }, x: 0 },
        { anchor: { x: 600, y: 40, width: 200, height: 60 }, x: 481 },
    ])('places an overlay beside its anchor, or over the detail pane ($x)', ({ anchor, x }) => {
        const regions: ReservedRegion[] = [
            { kind: 'division', frame: { x: 465, y: 0, width: 16, height: 669 }, occludesContent: false },
        ]
        expect(overlayPane(BOUNDS, regions, anchor).x).toBe(x)
    })

    test('keeps a floating surface below an interior camera region', () => {
        expect(overlayPane(BOUNDS, [{ kind: 'occlusion', frame: { x: 400, y: 0, width: 60, height: 80 } }])).toEqual({
            x: 0,
            y: 80,
            width: 867,
            height: 589,
        })
    })
})
