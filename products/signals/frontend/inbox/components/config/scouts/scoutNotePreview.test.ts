import { NOTE_PREVIEW_CHARS, scoutNotePreview } from './scoutNotePreview'

describe('scoutNotePreview', () => {
    it('leaves a note that already fits', () => {
        expect(scoutNotePreview('Watch conversion closely this week.')).toBe('Watch conversion closely this week.')
    })

    it.each([
        ['spaces', ' '],
        ['newlines', '\n'],
    ])('backs up to the last whitespace when words are separated by %s', (_name, separator) => {
        const preview = scoutNotePreview(`${`alpha${separator}`.repeat(60)}omega`)

        expect(preview.endsWith('alpha…')).toBe(true)
    })

    it.each([
        // Each of these puts the limit inside a character: the first halfway through a surrogate
        // pair, the second inside a family emoji, which is seven code points joined together.
        ['a surrogate pair', 'a', '🙂'],
        ['a joined emoji', 'x'.repeat(NOTE_PREVIEW_CHARS - 1), '👨‍👩‍👧‍👦'],
    ])('keeps %s whole when there is no whitespace to back up to', (_name, lead, character) => {
        const filler = character.repeat(NOTE_PREVIEW_CHARS)

        expect(scoutNotePreview(`${lead}${filler}`)).toBe(
            `${lead}${character.repeat(NOTE_PREVIEW_CHARS - Array.from(lead).length)}…`
        )
    })

    it.each([
        ['a URL', `https://example.com/${'segment/'.repeat(50)}`],
        ['an email address', `someone@example.${'a'.repeat(300)}`],
    ])('drops %s rather than cutting one', (_name, link) => {
        // Without a space in front of it there is nothing to back up to, so the link is the only
        // thing the preview can drop. A cut one would still render as a link, to the wrong place.
        expect(scoutNotePreview(`${'あ'.repeat(200)}${link}`)).toBe(`${'あ'.repeat(200)}…`)
        expect(scoutNotePreview(link)).toBe('…')
    })

    it.each([
        // Each of these used to shrink the preview for nothing: the first backed up 275 characters
        // to the one space, the second read `build@…` as an address, the third read `s3://…` as a
        // link, and the fourth measured the last word in code units so a nearby space looked far.
        ['the last whitespace sits far behind the cut', `Note: ${'あ'.repeat(400)}`, `Note: ${'あ'.repeat(274)}…`],
        [
            'an @ runs past the cut with no domain after it',
            `${'あ'.repeat(200)}build@${'a'.repeat(200)}`,
            `${'あ'.repeat(200)}build@${'a'.repeat(74)}…`,
        ],
        [
            'a scheme GFM never autolinks runs past the cut',
            `${'あ'.repeat(200)}s3://bucket/${'x'.repeat(200)}`,
            `${'あ'.repeat(200)}s3://bucket/${'x'.repeat(68)}…`,
        ],
        [
            'the last word is non-BMP but the space is within reach',
            `${'a'.repeat(249)} ${'𐐀'.repeat(100)}`,
            `${'a'.repeat(249)}…`,
        ],
    ])('fills the preview when %s', (_name, content, expected) => {
        expect(scoutNotePreview(content)).toBe(expected)
    })

    it('shows the note in full in a browser with no grapheme segmenter', async () => {
        // The panel is one import away from every scout page, so a segmenter built at module scope
        // takes the page down on a browser that has none. Without one, show the note in full rather
        // than risk a code-point cut splitting a character.
        const intl = Intl as { Segmenter?: typeof Intl.Segmenter }
        const segmenter = intl.Segmenter
        try {
            delete intl.Segmenter
            jest.resetModules()
            const { scoutNotePreview: withoutSegmenter } = await import('./scoutNotePreview')
            const note = '👨‍👩‍👧‍👦'.repeat(NOTE_PREVIEW_CHARS + 1)

            expect(withoutSegmenter(note)).toBe(note)
        } finally {
            intl.Segmenter = segmenter
            jest.resetModules()
        }
    })
})
