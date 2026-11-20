import { grantSlots } from './ChartCanvasBudget'

const slots = new Map(Array.from({ length: 10 }, (_, index) => [`pin-${index}`, index]))

describe('grantSlots', () => {
    test.each<[string, string[], number, string[], boolean?]>([
        ['without visibility the first items win', [], 3, ['pin-0', 'pin-1', 'pin-2']],
        ['visible items win, then the nearest ones', ['pin-5', 'pin-6'], 4, ['pin-4', 'pin-5', 'pin-6', 'pin-7']],
        [
            'a budget smaller than the screen keeps the earlier visible items',
            ['pin-2', 'pin-3', 'pin-4'],
            2,
            ['pin-2', 'pin-3'],
        ],
        ['keys the list reports but no chart registered are ignored', ['header', 'pin-9'], 2, ['pin-8', 'pin-9']],
        ['visible cards win across gaps in stable slot order', ['pin-2', 'pin-9'], 2, ['pin-2', 'pin-9'], true],
        ['the default keeps the existing range priority', ['pin-2', 'pin-9'], 2, ['pin-2', 'pin-3']],
    ])('%s', (_, visibleKeys, max, expected, prioritizeVisible = false) => {
        expect([...grantSlots(slots, visibleKeys, max, prioritizeVisible)].sort()).toEqual(expected.sort())
    })
})
