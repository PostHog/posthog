import {
    type ContextMenuPlacement,
    type ContextMenuPlacementInput,
    placeAnchoredMenu,
    placeContextMenu,
} from './contextMenuPlacement'

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

test.each([0, 84])('keeps a row menu aligned inside a host shifted %s points', (x) => {
    expect(
        placeAnchoredMenu({
            anchor: { x: x + 24, y: 220, width: 300, height: 50 },
            frame: { x, y: 20, width: 400, height: 700 },
            pane: { x: 0, y: 0, width: 400, height: 700 },
            width: 272,
            height: 300,
        })
    ).toMatchObject({ left: 24, top: 258, width: 272 })
})

test('constrains a tall menu to the anchored side of a fold', () => {
    const menu = placeAnchoredMenu({
        anchor: { x: 540, y: 300, width: 300, height: 50 },
        frame: { x: 84, y: 0, width: 867, height: 669 },
        pane: { x: 450, y: 0, width: 417, height: 320 },
        width: 500,
        height: 600,
    })
    expect(menu.left).toBeGreaterThanOrEqual(464)
    expect(menu.left + menu.width).toBeLessThanOrEqual(853)
    expect(menu.top + menu.maxHeight).toBeLessThanOrEqual(306)
})
