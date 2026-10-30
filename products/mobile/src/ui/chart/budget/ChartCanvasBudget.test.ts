import { grantSlots } from './ChartCanvasBudget'

const slots = new Map(Array.from({ length: 10 }, (_, index) => [`pin-${index}`, index]))

describe('grantSlots', () => {
    test.each<[string, string[], number, string[]]>([
        ['without visibility the first items win', [], 3, ['pin-0', 'pin-1', 'pin-2']],
        ['visible items win, then the nearest ones', ['pin-5', 'pin-6'], 4, ['pin-4', 'pin-5', 'pin-6', 'pin-7']],
        [
            'a budget smaller than the screen keeps the earlier visible items',
            ['pin-2', 'pin-3', 'pin-4'],
            2,
            ['pin-2', 'pin-3'],
        ],
        ['keys the list reports but no chart registered are ignored', ['header', 'pin-9'], 2, ['pin-8', 'pin-9']],
    ])('%s', (_, visibleKeys, max, expected) => {
        expect([...grantSlots(slots, visibleKeys, max)].sort()).toEqual(expected.sort())
    })
})
