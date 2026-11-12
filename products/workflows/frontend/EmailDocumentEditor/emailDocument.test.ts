import { EMAIL_DOCUMENT_VERSION, emailDocumentFromValue, emptyEmailDoc, withoutEmailDocument } from './emailDocument'

const wrap = (html: string): Record<string, any> => ({
    body: { rows: [{ columns: [{ contents: [{ type: 'html', values: { html } }] }] }] },
})
const stored = { version: EMAIL_DOCUMENT_VERSION, doc: emptyEmailDoc() }

describe('emailDocumentFromValue', () => {
    it.each([
        {
            name: 'html that matches what the document rendered opens the document',
            value: { html: '<p>a</p>', design: { ...wrap('<p>a</p>'), emailDocument: stored } },
            expected: { document: stored, stale: false },
        },
        {
            name: 'html changed elsewhere makes the document stale, so it can never overwrite that change',
            value: { html: '<p>changed</p>', design: { ...wrap('<p>a</p>'), emailDocument: stored } },
            expected: { document: null, stale: true },
        },
        {
            name: 'html cleared by writing in the plain text tab keeps the document open',
            value: { html: '', design: { ...wrap('<p>a</p>'), emailDocument: stored } },
            expected: { document: stored, stale: false },
        },
        {
            name: 'an old-editor design has no document',
            value: { html: '<p>a</p>', design: wrap('<p>a</p>') },
            expected: { document: null, stale: false },
        },
        {
            name: 'a document from a newer version of the editor is not read',
            value: { html: '<p>a</p>', design: { ...wrap('<p>a</p>'), emailDocument: { ...stored, version: 99 } } },
            expected: { document: null, stale: false },
        },
        { name: 'no value', value: null, expected: { document: null, stale: false } },
    ])('$name', ({ value, expected }) => {
        expect(emailDocumentFromValue(value)).toEqual(expected)
    })

    it('leaves a design without a document untouched', () => {
        const design = wrap('<p>a</p>')

        expect(withoutEmailDocument(design)).toBe(design)
        expect(withoutEmailDocument({ ...design, emailDocument: stored })).toEqual(design)
    })
})
