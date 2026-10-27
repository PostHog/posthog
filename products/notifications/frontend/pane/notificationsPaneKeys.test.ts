import { nextRowIndex, rowCommandForKey } from './notificationsPaneKeys'

describe('notificationsPaneKeys', () => {
    it.each([
        ['ArrowDown', 1, 2],
        ['j', 1, 2],
        ['ArrowUp', 1, 0],
        ['k', 0, 0],
        ['j', 2, 2],
        ['Enter', 1, null],
    ])('%s from row %s moves to %s', (key, current, expected) => {
        expect(nextRowIndex(current, 3, key)).toBe(expected)
    })

    it.each([
        ['e', false, 'archive'],
        ['E', true, 'undo_archive'],
        ['u', false, 'toggle_read'],
        ['U', true, null],
        ['x', false, null],
    ])('%s with shift %s runs %s', (key, shiftKey, expected) => {
        expect(rowCommandForKey(key, shiftKey)).toBe(expected)
    })
})
