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

    it('keeps whole characters when there is no whitespace to back up to', () => {
        // The leading character puts the limit halfway through an emoji, which is where cutting by
        // UTF-16 code unit leaves half a character behind.
        const preview = scoutNotePreview(`a${'🙂'.repeat(NOTE_PREVIEW_CHARS)}`)

        expect(preview).toBe(`a${'🙂'.repeat(NOTE_PREVIEW_CHARS - 1)}…`)
    })

    it('drops a URL rather than cutting one', () => {
        const url = `https://example.com/${'segment/'.repeat(50)}`

        expect(scoutNotePreview(`Read this: ${url}`)).toBe('Read this:…')
        expect(scoutNotePreview(url)).toBe('…')
    })
})
