import { type ContextMenuPlacement, type ContextMenuPlacementInput, placeContextMenu } from './contextMenuPlacement'

const limits = { topLimit: 100, bottomLimit: 700 }

describe('placeContextMenu', () => {
    test.each<[string, ContextMenuPlacementInput, ContextMenuPlacement]>([
        // Catches a menu that opens over the row it acts on, or ignores the gap.
        [
            'fits below the row',
            { ...limits, rowTop: 200, rowBottom: 271, menuHeight: 300 },
            { top: 279, side: 'below' },
        ],
        // Catches a menu on a low row that hides under the bottom bar instead of flipping.
        [
            'flips above a low row',
            { ...limits, rowTop: 560, rowBottom: 631, menuHeight: 300 },
            { top: 252, side: 'above' },
        ],
        // Catches a menu that runs past the bottom bar when a tall menu fits on neither side.
        [
            'clamps on the roomier side below',
            { ...limits, rowTop: 300, rowBottom: 371, menuHeight: 420 },
            { top: 280, side: 'below' },
        ],
        // Catches a menu that slides under the header when a tall menu fits on neither side.
        [
            'clamps on the roomier side above',
            { ...limits, rowTop: 420, rowBottom: 491, menuHeight: 420 },
            { top: 100, side: 'above' },
        ],
        // Catches a menu taller than the whole space that starts above the header.
        [
            'pins a menu taller than the space to the top limit',
            { ...limits, rowTop: 300, rowBottom: 371, menuHeight: 700 },
            { top: 100, side: 'below' },
        ],
    ])('%s', (_name, input, expected) => {
        expect(placeContextMenu(input)).toEqual(expected)
    })
})
