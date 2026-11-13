import { type RowScrollInput, rowScrollTarget } from './rowScroll'

// A 844 pt viewport, the map block at 160 pt and 200 pt tall, stuck at 104 pt, and 44 pt rows from 420 pt down.
const BASE: Omit<RowScrollInput, 'rowTop' | 'scrollY'> = {
    rowHeight: 44,
    blockTop: 160,
    blockHeight: 200,
    stickTop: 104,
    viewportHeight: 844,
    contentHeight: 2000,
}

describe('rowScrollTarget', () => {
    test.each([
        ['a row already on screen stays put', 420, 0, null],
        ['a row below the screen lands under the stuck block', 1400, 0, 1088],
        ['a row hidden under the stuck block comes back out', 600, 400, 288],
        ['a row near the end stops at the end of the content', 1950, 0, 1156],
    ])('%s', (_name, rowTop, scrollY, expected) => {
        expect(rowScrollTarget({ ...BASE, rowTop, scrollY })).toBe(expected)
    })
})
