import { denseRanks, movedOrder, prunedPrefs, usePinPrefs } from './pinPrefsStore'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)

describe('pin prefs', () => {
    test.each<[string, string, -1 | 1, string[]]>([
        ['moves a pin up', 'c', -1, ['a', 'c', 'b']],
        ['moves a pin down', 'a', 1, ['b', 'a', 'c']],
        ['keeps the first pin when it moves up', 'a', -1, ['a', 'b', 'c']],
        ['keeps the last pin when it moves down', 'c', 1, ['a', 'b', 'c']],
    ])('%s with dense ranks for the shown order', (_name, id, direction, expected) => {
        const next = movedOrder(['a', 'b', 'c'], id, direction)

        expect(next).toEqual(expected)
        expect(denseRanks(next)).toEqual(Object.fromEntries(expected.map((key, index) => [key, index])))
    })

    test('forgets pins that left the list only when the list was complete', () => {
        const prefs = { rank: { a: 0, gone: 1 }, display: { gone: { mode: 'number' as const } } }

        expect(prunedPrefs(prefs, ['a'], false)).toBe(prefs)
        expect(prunedPrefs(prefs, ['a'], true)).toEqual({ rank: { a: 0 }, display: {} })
        // A read that removes nothing keeps the same prefs, so no pin card re-renders.
        expect(prunedPrefs(prefs, ['a', 'gone', 'new'], true)).toBe(prefs)
    })

    test('a complete pin list of one project keeps the order and modes of another', () => {
        const store = usePinPrefs.getState()
        store.setOrder('us|1', ['a2', 'a1'])
        store.setDisplay('us|1', 'a1', { mode: 'chart' })

        store.prune('us|2', ['b1'], true)

        expect(usePinPrefs.getState().projects['us|1']).toEqual({
            rank: { a2: 0, a1: 1 },
            display: { a1: { mode: 'chart' } },
        })
        usePinPrefs.getState().clear()
    })
})
