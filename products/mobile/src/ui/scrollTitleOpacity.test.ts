import { scrollTitleOpacity } from './scrollTitleOpacity'

describe('scroll title visibility', () => {
    it.each([
        ['before the title is measured', 80, 0, 0],
        ['during pull to refresh', -40, 50, 0],
        ['at rest', 0, 50, 0],
        ['before the title reaches the header', 22, 50, 0],
        ['while the title passes under the header', 36, 50, 0.5],
        ['after the title leaves the content', 50, 50, 1],
        ['after scrolling farther', 200, 50, 1],
        ['with a short title', 5, 10, 0.5],
        ['with a wrapped title', 106, 120, 0.5],
    ])('%s', (_description, scrollY, revealEnd, opacity) => {
        expect(scrollTitleOpacity(scrollY, revealEnd)).toBe(opacity)
    })
})
