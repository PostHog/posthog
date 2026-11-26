import { pagerState } from './aiVisibilityTablePaging'

describe('pagerState', () => {
    test.each([
        { name: 'keeps a page that still has rows', autoPage: 2, rowCount: 12, page: 2, slice: [5, 10] },
        { name: 'falls back to the last page when rows leave', autoPage: 2, rowCount: 5, page: 1, slice: [0, 5] },
        { name: 'stays on page 1 when the list empties', autoPage: 3, rowCount: 0, page: 1, slice: [0, 5] },
    ])('$name', ({ autoPage, rowCount, page, slice }) => {
        const state = pagerState({ pageSize: 5 }, autoPage, rowCount)
        expect({ page: state.page, slice: state.slice }).toEqual({ page, slice })
    })
})
