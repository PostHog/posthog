import { reportQueuePosition } from './reportQueue'

describe('reportQueuePosition', () => {
    test.each([
        ['the first report', 'a', { position: 1, total: 54, previousId: null, nextId: 'b' }],
        ['a middle report', 'b', { position: 2, total: 54, previousId: 'a', nextId: 'c' }],
        ['the last loaded report', 'c', { position: 3, total: 54, previousId: 'b', nextId: null }],
        ['a report that the list does not hold', 'z', null],
    ])('%s', (_name, id, expected) => {
        expect(reportQueuePosition(['a', 'b', 'c'], 54, id)).toEqual(expected)
    })

    it('never counts fewer reports than the list holds', () => {
        expect(reportQueuePosition(['a', 'b', 'c'], 0, 'c')?.total).toBe(3)
    })
})
