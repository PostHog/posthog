import { CommandCenterCells, placeSession, resizeCells } from './commandCenterGrid'

describe('commandCenterGrid', () => {
    test.each<[string, CommandCenterCells, number, CommandCenterCells]>([
        ['grows with empty tiles', ['a', null], 4, ['a', null, null, null]],
        ['moves cut-off sessions into empty tiles', ['a', null, null, 'b', null, 'c'], 2, ['a', 'b']],
        ['keeps sessions in place when they fit', [null, 'a', 'b', null], 4, [null, 'a', 'b', null]],
        ['drops sessions only when every tile is full', ['a', 'b', 'c', 'd'], 2, ['a', 'b']],
    ])('resizeCells %s', (_, cells, count, expected) => {
        expect(resizeCells(cells, count)).toEqual(expected)
    })

    test('placeSession empties the tile the session was in before', () => {
        expect(placeSession(['a', null, 'b', null], 3, 'a')).toEqual([null, null, 'b', 'a'])
    })
})
