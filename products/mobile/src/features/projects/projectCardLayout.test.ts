import { projectCardLayout } from './projectCardLayout'

describe('projectCardLayout', () => {
    test.each([
        ['a 388pt card on an 874pt phone keeps the regular layout', 388, 874, { compact: false, footerPinned: true }],
        [
            'a 287pt card on a 568pt phone with the keyboard up turns compact to keep two rows above the footer',
            287,
            568,
            { compact: true, footerPinned: true },
        ],
    ])('%s', (_name, cardHeight, windowHeight, layout) => {
        expect(projectCardLayout(cardHeight, windowHeight, true)).toEqual(layout)
    })
})
