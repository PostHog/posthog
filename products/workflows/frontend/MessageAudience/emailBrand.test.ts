import { EmailBrand, applyEmailBrand } from './emailBrand'
import { draftMessage, messageDraftEmail } from './messageDrafts'

const block = (inner: string): string =>
    `<table role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0"><tbody><tr><td style="padding:10px;font-family:georgia;">${inner}</td></tr></tbody></table>`

const BRAND: EmailBrand = {
    source: 'template',
    design: {
        counters: { u_content_text: 2 },
        body: {
            values: { backgroundColor: '#fdf6e3' },
            rows: [
                {
                    columns: [
                        {
                            contents: [
                                { type: 'image', values: { src: { url: 'https://example.com/logo.png' } } },
                                { type: 'heading', values: { text: 'Template headline' } },
                                {
                                    type: 'text',
                                    values: {
                                        text: '<p>Template body copy that is the longest text here.</p>',
                                        color: '#123456',
                                    },
                                },
                                { type: 'text', values: { text: '<p>Short note</p>' } },
                                { type: 'custom', values: { unsubscribe: true } },
                            ],
                        },
                    ],
                },
            ],
        },
    },
    html: `<html><body style="background-color:#fdf6e3"><div class="u-row-container"><div class="u-row"><div class="u-col u-col-100"><div><div>${[
        block('<img src="https://example.com/logo.png" />'),
        block('<h1>Template headline</h1>'),
        block('<div style="color:#123456"><p>Template body copy that is the longest text here.</p></div>'),
        block('<div><p>Short note</p></div>'),
        block('<a href="{{ unsubscribe_url }}">Unsubscribe</a>'),
    ].join('')}</div></div></div></div></div></body></html>`,
}

describe('applyEmailBrand', () => {
    it('puts the draft in place of the template wording and keeps the rest of the brand', () => {
        const draft = draftMessage({ kind: 'issue_fixed' })
        const branded = applyEmailBrand(messageDraftEmail(draft), BRAND)!

        const contents = branded.design.body.rows[0].columns[0].contents
        expect(contents.map((content: any) => content.type)).toEqual([
            'image',
            ...draft.paragraphs.map(() => 'text'),
            'custom',
        ])
        expect(contents[1].values.color).toEqual('#123456')
        expect(branded.design.body.values.backgroundColor).toEqual('#fdf6e3')
        for (const paragraph of draft.paragraphs) {
            expect(branded.html).toContain(paragraph)
        }
        expect(branded.html).toContain('https://example.com/logo.png')
        expect(branded.html).toContain('{{ unsubscribe_url }}')
        expect(branded.html).toContain('color:#123456')
        expect(branded.html).not.toContain('Template')
        expect(branded.html).not.toContain('Short note')
    })

    it.each([
        { case: 'html the visual editor did not export', brand: { ...BRAND, html: '<p>Hand written</p>' } },
        { case: 'a design with no text block', brand: { ...BRAND, design: { body: { rows: [] } } } },
    ])('leaves the draft unbranded for $case', ({ brand }) => {
        expect(applyEmailBrand(messageDraftEmail(draftMessage({ kind: 'issue_fixed' })), brand)).toBeNull()
    })
})
