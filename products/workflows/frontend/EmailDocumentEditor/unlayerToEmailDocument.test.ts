import { emailDocumentToUnlayer } from './emailDocumentToUnlayer'
import { renderEmailHtml } from './renderEmailHtml'
import { unlayerToEmailDocument } from './unlayerToEmailDocument'

jest.mock('./components/EmailHtmlBlockView', () => ({ EmailHtmlBlockView: () => null }))
jest.mock('./components/EmailImageBlockView', () => ({ EmailImageBlockView: () => null }))
jest.mock('./components/EmailVariableChip', () => ({ EmailVariableChip: () => null }))

const content = (type: string, values: Record<string, any>, extra: Record<string, any> = {}): Record<string, any> => ({
    id: `${type}-1`,
    type,
    values,
    ...extra,
})

function design(
    contents: Record<string, any>[],
    rowValues: Record<string, any> = {},
    columnValues: Record<string, any> = {}
): Record<string, any> {
    return {
        body: {
            values: { contentWidth: '500px', backgroundColor: '#ffffff' },
            rows: [{ id: 'r', cells: [1], values: rowValues, columns: [{ id: 'c', values: columnValues, contents }] }],
        },
    }
}

describe('unlayerToEmailDocument', () => {
    it.each([
        { type: 'timer', reason: 'countdown timers' },
        { type: 'video', reason: 'videos' },
        { type: 'somethingNew', reason: 'somethingNew blocks' },
    ])('reports a $type block instead of dropping it', ({ type, reason }) => {
        expect(unlayerToEmailDocument(design([content(type, {})]))).toEqual({
            document: null,
            unsupported: [reason],
            notKept: [],
        })
    })

    it.each([
        {
            name: 'a condition on a block',
            contents: [content('text', { text: '<p>x</p>', displayCondition: { type: 'a' } })],
            rowValues: {},
        },
        {
            name: 'a condition on a row',
            contents: [content('text', { text: '<p>x</p>' })],
            rowValues: { displayCondition: { type: 'a' } },
        },
        {
            name: 'a background image',
            contents: [content('text', { text: '<p>x</p>' })],
            rowValues: { backgroundImage: { url: 'https://example.com/a.png' } },
        },
    ])('keeps an email with $name on the old editor', ({ contents, rowValues }) => {
        const { document, unsupported } = unlayerToEmailDocument(design(contents, rowValues))

        expect(document).toBeNull()
        expect(unsupported).toHaveLength(1)
    })

    it('uses the background every row shares as the page, so the band around the email survives', () => {
        const { document } = unlayerToEmailDocument(
            design(
                [content('text', { text: '<p>x</p>' })],
                { backgroundColor: '#eeefe8' },
                { backgroundColor: '#ffffff' }
            )
        )

        expect(document?.doc.attrs?.page).toMatchObject({
            backgroundColor: '#eeefe8',
            bodyBackgroundColor: '#ffffff',
            bodyWidth: 500,
        })
        expect(document?.doc.content?.[0].type).toEqual('paragraph')
    })

    it.each([
        { name: 'the body color', rowBackground: '', spacerAttrs: { height: 8 } },
        {
            name: 'a row color',
            rowBackground: '#ff0000',
            spacerAttrs: { height: 8, backgroundColor: '#ff0000' },
        },
    ])('shows $name in row padding around a columns color', ({ rowBackground, spacerAttrs }) => {
        const { document } = unlayerToEmailDocument(
            design([content('text', { text: '<p>x</p>' })], {
                padding: '8px 0px',
                backgroundColor: rowBackground,
                columnsBackgroundColor: '#00ff00',
            })
        )

        expect(document?.doc.content?.map((node) => node.type)).toEqual(['emailSpacer', 'emailColumns', 'emailSpacer'])
        expect(document?.doc.content?.[0].attrs).toEqual(spacerAttrs)
        expect(document?.doc.content?.[1].attrs?.emailStyle).toEqual({ backgroundColor: '#00ff00', columnGap: 0 })
    })

    it('turns Liquid in copy into variables, keeping its fallback and the marks around it', () => {
        const { document } = unlayerToEmailDocument(
            design([
                content('text', {
                    text: `<p>Hi <strong>{{ person.properties.name | default: 'you' }}</strong> {{- event.name -}}</p>`,
                }),
            ])
        )

        expect(document?.doc.content?.[0].content?.[1]).toMatchObject({
            type: 'variable',
            attrs: { expression: 'person.properties.name', fallback: 'you' },
            marks: [{ type: 'bold' }],
        })
        // A chip can't write Liquid's whitespace-trimming hyphens back, so that tag stays as written.
        expect(JSON.stringify(document?.doc)).toContain('{{- event.name -}}')
    })

    it.each([
        {
            name: 'in a paragraph',
            text: '<p>Open <a href="https://example.com/app" clicktracking="off">the app</a></p>',
        },
        {
            name: 'in a list item',
            text: '<ul><li><a href="https://example.com/app" data-ph-no-track>the app</a></li></ul>',
        },
        {
            name: 'in a heading',
            type: 'heading',
            text: 'Open <a href="https://example.com/app" ses:no-track>the app</a>',
        },
    ])(
        'keeps text with a link opted out of click tracking as written, $name, so the opt-out reaches the send',
        ({ text, type = 'text' }) => {
            const { document } = unlayerToEmailDocument(design([content(type, { text })]))

            expect(document?.doc.content?.[0]).toMatchObject({ type: 'emailHtml' })
            expect(document?.doc.content?.[0].attrs?.html).toMatch(/clicktracking="off"|data-ph-no-track|ses:no-track/)
        }
    )

    it("spreads a text block's padding over its paragraphs without doubling the gaps between them", () => {
        const { document } = unlayerToEmailDocument(
            design([content('text', { text: '<p>One</p><p>Two</p>', containerPadding: '10px' })])
        )

        expect(document?.doc.content?.map((node) => node.attrs?.emailStyle.padding)).toEqual([
            { top: 10, right: 10, bottom: 0, left: 10 },
            { top: 0, right: 10, bottom: 10, left: 10 },
        ])
    })

    it('keeps a social footer looking the same, as an HTML block whose icons wrap on a narrow screen', () => {
        const { document } = unlayerToEmailDocument(
            design([
                content('social', {
                    iconSize: 15,
                    icons: { iconType: 'circle-black', icons: [{ name: 'GitHub', url: 'https://example.com/gh' }] },
                }),
            ])
        )

        const node = document?.doc.content?.[0]
        expect(node?.type).toEqual('emailHtml')
        expect(node?.attrs?.html).toContain('social/icons/circle-black/github.png')
        expect(node?.attrs?.html).toContain('href="https://example.com/gh"')
        expect(node?.attrs?.html).toContain('style="display:inline-table;')
    })

    it('keeps a menu looking the same, as an HTML block, and an empty one as the space it took', () => {
        const link = (href: string): Record<string, any> => ({ name: 'web', values: { href, target: '_blank' } })
        const menu = (items: Record<string, any>[]): Record<string, any> | undefined =>
            unlayerToEmailDocument(
                design([
                    content('menu', {
                        menu: { items },
                        separator: '|',
                        linkColor: '#1d4aff',
                        padding: '5px 15px',
                        containerPadding: '10px',
                    }),
                ])
            ).document?.doc.content?.[0]

        const html = menu([
            { text: 'Blog', link: link('https://example.com/blog') },
            { text: 'A <b>"quote"</b>', link: link('https://example.com/?a=1&b="x"') },
        ])?.attrs?.html

        expect(html).toContain('<a href="https://example.com/blog" target="_blank" style="padding:5px 15px;')
        expect(html).toContain('color:#1d4aff')
        expect(html).toContain(
            '</a> <span class="hide-mobile" style="padding:5px 15px;display:inline-block;font-size:14px;color:#444444">|</span> <a'
        )
        expect(html).toContain('href="https://example.com/?a=1&amp;b=&quot;x&quot;"')
        expect(html).toContain('A &lt;b&gt;&quot;quote&quot;&lt;/b&gt;')
        expect(menu([])).toEqual({ type: 'emailSpacer', attrs: { height: 20 } })
    })

    it('expands the unsubscribe block', () => {
        const { document } = unlayerToEmailDocument(
            design([
                content(
                    'custom',
                    { unsubscribe_link_content: '<div><a href="{{ unsubscribe_url }}">Unsubscribe</a></div>' },
                    { slug: 'unsubscribe_link' }
                ),
            ])
        )

        expect(JSON.stringify(document?.doc)).toContain('"href":"{{ unsubscribe_url }}"')
    })

    it.each([
        [
            'button sides in different colors',
            content('button', {
                border: {
                    borderTopWidth: '1px',
                    borderTopColor: '#111111',
                    borderBottomWidth: '3px',
                    borderBottomColor: '#222222',
                },
            }),
            'buttons with a border on only some sides',
        ],
    ])('rebuilds an email with %s and no html, and says the border is dropped', (_name, block, reason) => {
        // An email saved only in plain text has a design but no html, so there is nothing else to fall back on.
        const conversion = unlayerToEmailDocument(design([block]), '')
        expect(conversion.document?.doc.content?.[0].type).toBe('emailButton')
        expect(conversion.notKept).toEqual([reason])
    })

    it('keeps a button with a thicker bottom edge as a button, with each side drawn as before', () => {
        const side = (width: string): Record<string, string> => ({ Width: width, Style: 'solid', Color: '#8a5a12' })
        const border = Object.fromEntries(
            Object.entries({ Top: '1px', Right: '1px', Bottom: '3px', Left: '1px' }).flatMap(([name, width]) =>
                Object.entries(side(width)).map(([key, value]) => [`border${name}${key}`, value])
            )
        )
        const conversion = unlayerToEmailDocument(
            design([
                content('text', { text: '<p>Book a call</p>' }),
                content('button', {
                    text: 'Pick a time',
                    href: { values: { href: 'https://example.com/book' } },
                    border,
                }),
            ])
        )
        const doc = conversion.document?.doc as Record<string, any>
        const button = doc.content.find((node: Record<string, any>) => node.type === 'emailButton')

        expect(conversion.keptAsHtml).toEqual([])
        expect(button.attrs.emailStyle).toMatchObject({
            borderSides: { top: 1, right: 1, bottom: 3, left: 1 },
            borderColor: '#8a5a12',
        })
        expect(button.attrs.emailStyle.borderWidth).toBeUndefined()
        const html = renderEmailHtml(doc)
        expect(html).toContain(
            'border-top:1px solid #8a5a12;border-right:1px solid #8a5a12;border-bottom:3px solid #8a5a12;border-left:1px solid #8a5a12'
        )
        expect(html).toContain('strokeweight="1px"')
        const back = JSON.stringify(emailDocumentToUnlayer(doc))
        expect(back).toContain('"borderBottomWidth":"3px"')
        expect(back).toContain('"borderTopWidth":"1px"')
    })

    it('keeps what real emails rely on: preview text, web fonts, button width and border, column border, tables in text', () => {
        const border = (width: string): Record<string, string> =>
            Object.fromEntries(
                ['Top', 'Right', 'Bottom', 'Left'].flatMap((side) => [
                    [`border${side}Width`, width],
                    [`border${side}Style`, 'solid'],
                    [`border${side}Color`, '#123456'],
                ])
            )
        const font = { label: 'Lato', value: 'Lato, sans-serif', url: 'https://fonts.example.com/lato.css' }
        const source = design(
            [
                content('text', { text: '<p>Words</p>', fontFamily: font }),
                content('text', { text: '<table><tr><td>Cell</td></tr></table>' }),
                content('button', {
                    text: 'Go',
                    size: { autoWidth: false, width: '100%' },
                    border: border('2px'),
                    buttonColors: { backgroundColor: '#111111', hoverBackgroundColor: '#222222' },
                }),
            ],
            {},
            { border: border('1px') }
        )
        source.body.values = { preheaderText: 'Peek', fontFamily: font }

        const conversion = unlayerToEmailDocument(source)
        const doc = conversion.document?.doc as Record<string, any>
        const [text, table, button] = doc.content[0].content[0].content

        expect(doc.attrs.page).toMatchObject({ previewText: 'Peek', fontFamily: font.value, fontUrl: font.url })
        expect(text.type).toBe('paragraph')
        expect(text.attrs.emailStyle.fontUrl).toBe(font.url)
        expect(table.type).toBe('emailHtml')
        expect(table.attrs.html).toContain('<td>Cell</td>')
        expect(button.attrs.emailStyle).toMatchObject({ buttonWidth: 100, borderWidth: 2, borderColor: '#123456' })
        expect(conversion.notKept).toEqual([])
    })

    it.each([
        {
            name: "a list's own indent and item spacing",
            block: content('text', {
                text: '<ul style="padding-left: 20px"><li style="margin-bottom: 8px">One</li><li style="margin-bottom: 8px">Two</li></ul>',
            }),
            exported: undefined,
            // The last item's 8px merges into the list's 14px bottom margin, so the cell adds only the difference.
            sent: [/padding:24px 10px 16px 10px[^"]*"><ul[^>]*margin:0 0 0 20px/, '<li style="margin:0 0 8px 0">'],
        },
        {
            name: 'a line height in pixels and tighter letter spacing',
            block: content('heading', { text: 'Title', fontSize: '32px', lineHeight: '40px', letterSpacing: '-0.5px' }),
            exported: undefined,
            sent: ['line-height:125%', 'letter-spacing:-0.5px'],
        },
        {
            name: 'bold text at its own weight',
            block: content('text', { text: '<p>A <strong style="font-weight: 600">semibold</strong> word</p>' }),
            exported: undefined,
            sent: ['<span style="font-weight:600">semibold</span>'],
        },
        {
            name: 'the size of an unsubscribe block',
            block: content('custom', { unsubscribe_link_content: '<div>Bye</div>' }, { slug: 'unsubscribe_link' }),
            exported: undefined,
            sent: ['font-size:16px;line-height:115%'],
        },
        {
            name: 'the size of text that earlier versions of the old editor left unset',
            block: content('text', { text: '<p>Plain</p>', lineHeight: '140%' }),
            exported:
                '<html><body><div class="u-row-container"><table><tr><td style="overflow-wrap:break-word;word-break:break-word;padding:10px;"><div style="line-height: 140%;"><p>Plain</p></div></td></tr></table></div></body></html>',
            sent: ['font-size:16px;line-height:140%'],
        },
        {
            name: 'a heading holding another heading, which browsers show at its own default size',
            block: content('heading', { text: '<h1>Big</h1>', fontSize: '22px' }),
            exported: undefined,
            sent: ['<h1 style="margin:0;font-size:22px;font-weight:400;line-height:140%"><h1>Big</h1></h1>'],
        },
        {
            name: 'the browser margins of paragraphs, when its html never reset them',
            block: content('text', { text: '<p>One</p><p>Two</p>', fontSize: '14px' }),
            exported:
                '<html><head><style>table, td { color: #000; }</style></head><body><div class="u-row-container"><table><tr><td style="overflow-wrap:break-word;word-break:break-word;padding:10px;"><div style="font-size: 14px;"><p>One</p><p>Two</p></div></td></tr></table></div></body></html>',
            sent: ['padding:24px 10px 0px 10px', 'padding:14px 10px 24px 10px'],
        },
        {
            name: 'no margins for text it sent without paragraphs, even when its html never reset them',
            block: content('text', { text: '<p>One</p><p>Two</p>', fontSize: '14px' }),
            exported:
                '<html><head><style>table, td { color: #000; }</style></head><body><div class="u-row-container"><table><tr><td style="overflow-wrap:break-word;word-break:break-word;padding:10px;"><div style="font-size: 14px;"><div>One</div><div>Two</div></div></td></tr></table></div></body></html>',
            sent: ['padding:10px 10px 0px 10px', 'padding:0px 10px 10px 10px'],
        },
        {
            name: "code in the email app's own monospace font",
            block: content('text', { text: '<p>Run <code>make</code></p>' }),
            exported: undefined,
            sent: ['Run <code>make</code>'],
        },
        {
            name: 'a button with no alignment, which the old editor centers',
            block: content('button', { text: 'Go' }),
            exported: undefined,
            sent: ['<tr><td align="center" style="padding:10px 10px 10px 10px;text-align:center">'],
        },
    ])('keeps $name as the old editor sent it', ({ block, exported, sent }) => {
        const html = renderEmailHtml(unlayerToEmailDocument(design([block]), exported).document?.doc ?? {})

        for (const expected of sent) {
            expect(html).toMatch(expected)
        }
    })

    it.each([
        {
            name: 'its export has a hover rule for it',
            exported: '#u_content_button_1 .v-button-colors:hover { color: #fff }',
            kept: '#222222',
        },
        // Most exports leave hover colors out, so adding them would change how those emails behave.
        { name: 'its export has no hover rule', exported: '.v-button { color: #fff }', kept: undefined },
    ])("keeps a button's hover color only when $name", ({ exported, kept }) => {
        const button = content('button', {
            text: 'Go',
            buttonColors: { backgroundColor: '#111111', hoverBackgroundColor: '#222222' },
            _meta: { htmlID: 'u_content_button_1' },
        })
        const html = `<html><head><style>${exported}</style></head><body><div class="u-row-container">Go</div></body></html>`

        const [converted] = unlayerToEmailDocument(design([button]), html).document?.doc.content as Record<
            string,
            any
        >[]

        expect(converted.attrs.emailStyle.hoverBackgroundColor).toEqual(kept)
    })

    it('keeps right-to-left text as its own markup with the direction on it', () => {
        const [block] = unlayerToEmailDocument(design([content('text', { text: '<p dir="rtl">שלום</p>' })])).document
            ?.doc.content as Record<string, any>[]

        expect(block.type).toBe('emailHtml')
        expect(block.attrs.html).toContain('<div dir="rtl"><p dir="rtl">שלום</p></div>')
    })

    it('keeps who sees a block or a row: its Liquid condition and the screens it is hidden on', () => {
        const condition = {
            type: 'paid',
            label: 'Paying customers',
            description: '',
            before: '{% if person.properties.plan == "paid" %}',
            after: '{% endif %}',
        }
        const { document } = unlayerToEmailDocument(
            design(
                [
                    content('text', {
                        text: '<p>Thanks for paying</p>',
                        displayCondition: condition,
                        hideMobile: true,
                    }),
                    content('text', { text: '<p>Everyone</p>' }),
                ],
                { hideDesktop: true, displayCondition: { ...condition, label: 'Row rule' } }
            ),
            // The old editor's export puts each condition around a row's markup, not between table rows.
            `<html><body>${condition.before}<div class="u-row-container hide-desktop"><div class="hide-mobile">${condition.before}<p>Thanks for paying</p>${condition.after}<p>Everyone</p></div></div>${condition.after}</body></html>`
        )
        const [section] = document?.doc.content as Record<string, any>[]
        const [paid, everyone] = section.content[0].content

        expect(section.type).toBe('emailColumns')
        expect(section.attrs.emailVisibility).toEqual({
            condition: { label: 'Row rule', before: condition.before, after: condition.after },
            hideDesktop: true,
        })
        expect(paid.attrs.emailVisibility).toEqual({
            condition: { label: 'Paying customers', before: condition.before, after: condition.after },
            hideMobile: true,
        })
        expect(everyone.attrs.emailVisibility).toBeFalsy()
    })

    it("drops a screen-size setting the old editor's html never carried out", () => {
        const { document } = unlayerToEmailDocument(
            design([content('text', { text: '<p>Hidden on phones</p>', hideMobile: true })], { hideDesktop: true }),
            '<html><body><div class="u-row-container"><p>Hidden on phones</p></div></body></html>'
        )

        expect(document?.doc.content?.[0].attrs?.emailVisibility).toBeFalsy()
    })

    it.each([
        { name: 'a video', block: content('video', { videoUrl: { url: 'https://example.com/v' } }), reason: 'videos' },
        { name: 'a table', block: content('table', {}), reason: 'tables' },
        { name: 'a block type it has never seen', block: content('somethingNew', {}), reason: 'somethingNew blocks' },
    ])("keeps a row with $name as the old editor's own html, and rebuilds the rest", ({ block, reason }) => {
        const twoRows = design([content('text', { text: '<p>Intro</p>' })])
        twoRows.body.rows.push({
            id: 'r2',
            cells: [1],
            values: {},
            columns: [{ id: 'c2', values: {}, contents: [block] }],
        })
        const exported = `<html><head><style>.u-row .u-col-100 { width: 500px !important; }</style></head><body>
<div class="u-row-container" style="padding:0px"><p>Intro</p></div>
<div class="u-row-container" style="padding:4px 16px"><div class="u-row"><a href="https://example.com/v"><img src="https://example.com/thumb.png" /></a></div></div>
</body></html>`

        const conversion = unlayerToEmailDocument(twoRows, exported)
        const [intro, kept] = conversion.document?.doc.content as Record<string, any>[]

        expect(intro.type).toBe('paragraph')
        expect(kept.type).toBe('emailHtml')
        expect(kept.attrs.html).toBe(
            '<div class="u-row-container" style="padding: 4px 0px 4px 0px"><div class="u-row"><a href="https://example.com/v"><img src="https://example.com/thumb.png"></a></div></div>'
        )
        expect(conversion.document?.doc.attrs?.page.globalCss).toContain('.u-col-100')
        expect(conversion.keptAsHtml).toEqual([reason])
    })

    it.each([
        { name: 'no design at all', design: null },
        { name: 'an empty design', design: {} },
    ])('opens an email with $name and no html as a blank email', ({ design: empty }) => {
        expect(unlayerToEmailDocument(empty, '').document?.doc).toEqual({
            type: 'doc',
            attrs: { page: {} },
            content: [{ type: 'paragraph' }],
        })
    })

    it.each([
        {
            name: "its rows can't be matched to the design",
            block: content('video', {}),
            body: '<table><tr><td>Only one export</td></tr></table>',
            reason: 'videos',
        },
        {
            // The html was changed after the design, for example through the API, so the design shows older words.
            name: 'the design no longer matches it',
            block: content('text', { text: '<p>Words from before</p>' }),
            body: '<div class="u-row-container"><p>Words since</p></div>',
            reason: 'a design that no longer matches the email',
        },
    ])("sends the old editor's html unchanged when $name", ({ block, body, reason }) => {
        const exported = `<!DOCTYPE html><html><body>${body}</body></html>`

        const conversion = unlayerToEmailDocument(design([block]), `${exported}\n`)

        expect(renderEmailHtml(conversion.document?.doc ?? {})).toBe(exported)
        expect(conversion.keptAsHtml).toEqual([reason])
    })

    it("keeps the old editor's page styles for an HTML block holding its row markup, so the row shrinks on phones", () => {
        const html = '<div class="u-row" style="max-width:500px"><p>Pasted row</p></div>'
        const exported = `<html><head><style>@media (max-width: 520px) { .u-row { width: 100% !important; } }</style></head><body><div class="u-row-container">${html}</div></body></html>`

        const { document } = unlayerToEmailDocument(design([content('html', { html })]), exported)

        expect(document?.doc.attrs?.page.globalCss).toContain('.u-row { width: 100% !important; }')
    })

    it("sizes images as the old editor's html did and keeps its phone-only settings", () => {
        const image = (id: number): Record<string, any> =>
            content(
                'image',
                { src: { url: 'https://example.com/a.png', width: 320 }, _meta: { htmlID: `u_content_image_${id}` } },
                { id: `image-${id}` }
            )
        const blocks = [
            image(1),
            image(2),
            content('text', { text: '<p>Hello</p>', _meta: { htmlID: 'u_content_text_1' } }),
        ]
        const exported = `<html><head><style>@media (max-width: 480px) {
#u_content_image_2 .v-src-width { width: 40% !important; } #u_content_image_2 .v-src-max-width { max-width: 40% !important; }
#u_content_text_1 .v-container-padding-padding { padding: 4px 8px !important; } #u_content_text_1 .v-font-size { font-size: 12px !important; } }</style></head><body>
<div class="u-row-container">
<table id="u_content_image_1"><tr><td><!--[if mso]><img src="https://example.com/a.png" style="border: none;" width="320" height="200"/><![endif]--><img src="https://example.com/a.png" style="border: none;width: 50%;max-width: 160px;" width="160" class="v-src-width v-src-max-width"/></td></tr></table>
<table id="u_content_image_2"><tr><td><img src="https://example.com/a.png" style="border: none;float: none;" width="200" height="100" class="v-src-width v-src-max-width"/></td></tr></table>
<table id="u_content_text_1"><tr><td><p>Hello</p></td></tr></table>
</div></body></html>`

        const html = renderEmailHtml(unlayerToEmailDocument(design(blocks), exported).document?.doc ?? {})
        const images = [...html.matchAll(/<img [^>]*style="([^"]*)"/g)].map((match) => match[1])

        expect(images[0]).toContain('width:50%;max-width:160px')
        expect(images[1]).toContain('width:100%;max-width:200px')
        expect(html).toMatch(/\.ph-m-\d+ img \{ width: 40% !important; max-width: 40% !important;/)
        expect(html).toMatch(/\.ph-m-\d+ \{ padding:4px 8px 4px 8px !important; \}/)
        expect(html).toMatch(/\.ph-m-\d+ p, [^{]*\{ font-size:12px !important; \}/)
    })

    it("keeps the old editor's newer per-screen settings: hiding on phones, columns side by side and row padding", () => {
        const twoColumns = design([content('text', { text: '<p>Left</p>' })])
        twoColumns.body.rows[0] = {
            id: 'r',
            cells: [1, 1],
            values: { _meta: { htmlID: 'u_row_1' }, _override: { mobile: { noStackMobile: true } } },
            columns: [
                { id: 'a', values: {}, contents: [content('text', { text: '<p>Left</p>' })] },
                { id: 'b', values: {}, contents: [content('text', { text: '<p>Right</p>' })] },
            ],
        }
        twoColumns.body.rows.push({
            id: 'r2',
            cells: [1],
            values: {},
            columns: [
                {
                    id: 'c',
                    values: {},
                    contents: [
                        content('text', { text: '<p>Desktop only</p>', _override: { mobile: { hideMobile: true } } }),
                    ],
                },
            ],
        })
        const exported = `<html><head><style>@media (max-width: 480px) { #u_row_1 .v-row-padding--vertical { padding-top: 4px !important; padding-bottom: 6px !important; } }</style></head><body>
<div class="u-row-container"><p>Left</p><p>Right</p></div>
<div class="u-row-container"><table class="hide-mobile"><tr><td><p>Desktop only</p></td></tr></table></div>
</body></html>`

        const html = renderEmailHtml(unlayerToEmailDocument(twoColumns, exported).document?.doc ?? {})

        expect(html).toMatch(/<div style="display:inline-block;width:50%;/)
        expect(html).toMatch(/\.ph-m-\d+ \{ padding:4px 0px 6px 0px !important; \}/)
        expect(html).toContain('<tr class="ph-hide-mobile">')
    })

    it("follows the old editor's html where it disagrees with the design: body width and phone-only row and column settings", () => {
        const source = design(
            [content('text', { text: '<p>Hi</p>' })],
            { _meta: { htmlID: 'u_row_1' } },
            { _meta: { htmlID: 'u_column_1' } }
        )
        const exported = `<html><head><style>@media (min-width: 660px) { .u-row { width: 640px !important; } }
@media (max-width: 660px) { .u-row-container { padding-left: 0px !important; padding-right: 0px !important; } }
@media (max-width: 660px) { .u-row-container { padding-left: 16px !important; padding-right: 16px !important; } }
@media (max-width: 480px) { #u_row_1.v-row-padding--vertical { padding-top: 0px !important; padding-bottom: 0px !important; } #u_column_1 .v-col-border-radius { border-radius: 0px !important; } }</style></head>
<body><div class="u-row-container"><p>Hi</p></div></body></html>`

        const html = renderEmailHtml(unlayerToEmailDocument(source, exported).document?.doc ?? {})

        expect(html).toContain('max-width:640px;table-layout:fixed')
        expect(html).toMatch(/\.ph-m-\d+ \{ padding:0px 16px 0px 16px !important; \}/)
        expect(html).toMatch(/\.ph-m-\d+ \{ border-radius: 0px !important; \}/)
    })

    it('gives an email whose width is a percentage a standard body width', () => {
        const wide = design([content('text', { text: '<p>Hi</p>' })])
        wide.body.values.contentWidth = '100%'

        // The old editor exports such a design's rows as 100px wide.
        const exported =
            '<html><head><style>@media (min-width: 120px) { .u-row { width: 100px !important; } }</style></head><body><div class="u-row-container"><p>Hi</p></div></body></html>'

        expect(renderEmailHtml(unlayerToEmailDocument(wide, exported).document?.doc ?? {})).toContain('max-width:600px')
    })

    it('opens an email whose html the old editor did not write exactly as it is sent', () => {
        const stored = '<html><body><p style="color:#d00">Hello</p></body></html>'

        const conversion = unlayerToEmailDocument(design([content('text', { text: '<p>Hello</p>' })]), stored)

        expect(renderEmailHtml(conversion.document?.doc ?? {})).toBe(stored)
    })

    it('opens an email saved as raw html exactly as it is sent, even when it has no <html> tag', () => {
        const wrapped = design([content('html', { html: '<p>Hi</p>' })])
        wrapped.body.id = 'html-wrap-body'
        const stored = '<p style="color:#d00">Hi</p>'

        const conversion = unlayerToEmailDocument(wrapped, `${stored}\n`)

        expect(renderEmailHtml(conversion.document?.doc ?? {})).toBe(stored)
    })

    it('reads text kept only in textJson, and prefers text when a block has both', () => {
        const textJson = JSON.stringify({
            root: {
                type: 'root',
                children: [
                    { type: 'heading-paragraph', children: [{ type: 'extended-text', text: 'From json', format: 1 }] },
                ],
            },
        })
        const convert = (text: string): Record<string, any> | undefined =>
            unlayerToEmailDocument(design([content('heading', { text, textJson })])).document?.doc.content?.[0]

        expect(convert('')?.content).toEqual([expect.objectContaining({ text: 'From json' })])
        expect(convert('From text')?.content).toEqual([expect.objectContaining({ text: 'From text' })])
    })

    it.each([
        ['a plain string', '{{ link }}', '{{ link }}'],
        [
            'an email link without a template',
            { name: 'email', values: { href: 'a@example.com' } },
            'mailto:a@example.com',
        ],
        [
            'a template',
            { name: 'web', attrs: { href: '{{href}}' }, values: { href: 'https://example.com' } },
            'https://example.com',
        ],
        ['a template with no value', { name: 'web', attrs: { href: '{{href}}' }, values: {} }, ''],
    ])('resolves a button link written as %s', (_name, href, expected) => {
        const button = unlayerToEmailDocument(design([content('button', { text: 'Go', href })])).document?.doc
            .content?.[0]
        expect(button?.attrs?.href).toEqual(expected)
    })

    it('keeps the old editor defaults: regular headings, the email font for "inherit", percentages from bare line heights, and a 500px body', () => {
        const doc = unlayerToEmailDocument(
            design([
                content('heading', { text: 'Title', fontFamily: { label: 'Body Font', value: 'inherit' } }),
                content('text', { text: '<p>Body</p>', lineHeight: 1.6 }),
            ])
        ).document?.doc as Record<string, any>

        expect(doc.content[0].attrs.emailStyle.fontWeight).toBe(400)
        expect(doc.content[0].attrs.emailStyle.fontFamily).toBeUndefined()
        expect(doc.content[1].attrs.emailStyle.lineHeight).toBeCloseTo(160)
        expect(doc.attrs.page.bodyWidth).toBe(500)
    })

    it('keeps each paragraph margin as the space between blocks, and text it cannot hold as HTML', () => {
        const [first, second] = unlayerToEmailDocument(
            design([
                content('text', {
                    containerPadding: '10px',
                    text: '<p style="margin-bottom: 20px;">One</p><p style="margin-top: 5px;">Two</p>',
                }),
            ])
        ).document?.doc.content as Record<string, any>[]
        expect(first.attrs?.emailStyle.padding.bottom).toBe(0)
        expect(second.attrs?.emailStyle.padding.top).toBe(20)

        const blank = (inner: string): string[] =>
            (
                (unlayerToEmailDocument(design([content('text', { text: `<p>One</p><p>${inner}</p><p>Two</p>` })]))
                    .document?.doc.content ?? []) as Record<string, any>[]
            ).map((node) => node.content?.[0]?.type ?? 'empty')
        expect(blank('<span> </span>')).toEqual(['text', 'text'])
        expect(blank('&nbsp;')).toEqual(['text', 'text', 'text'])
        expect(blank('<br>')).toEqual(['text', 'hardBreak', 'text'])

        const [kept] = unlayerToEmailDocument(
            design([content('text', { text: '<p style="border-top: 1px solid red;">Ruled</p>' })])
        ).document?.doc.content as Record<string, any>[]
        expect(kept.type).toBe('emailHtml')
        expect(kept.attrs?.html).toContain('border-top: 1px solid red')
    })

    it("gives an image at its own size the old editor's automatic width, so it still fills a phone", () => {
        const image = (width: number): Record<string, any> => ({
            type: 'emailImage',
            attrs: { src: 'https://example.com/a.png', naturalWidth: 300, emailStyle: { width } },
        })
        const design = emailDocumentToUnlayer({ type: 'doc', attrs: { page: {} }, content: [image(300), image(150)] })
        const sources = design.body.rows.flatMap((row: any) =>
            row.columns.flatMap((column: any) => column.contents.map((content: any) => content.values.src))
        )

        expect(sources.map((src: any) => [src.autoWidth, src.maxWidth])).toEqual([
            [true, undefined],
            [false, '27.2%'],
        ])
    })

    it('keeps every block when an email goes to the old editor and comes back', () => {
        const text = (value: string): Record<string, any> => ({ type: 'text', text: value })
        const paragraph = (...nodes: Record<string, any>[]): Record<string, any> => ({
            type: 'paragraph',
            content: nodes,
        })
        const doc = {
            type: 'doc',
            attrs: {
                page: {
                    bodyWidth: 560,
                    backgroundColor: '#eeeeee',
                    bodyBackgroundColor: '#fafafa',
                    backgroundImage: {
                        url: 'https://example.com/bg.png',
                        repeat: true,
                        size: 'cover',
                        fullWidth: true,
                    },
                },
            },
            content: [
                { type: 'heading', attrs: { level: 1 }, content: [text('Rollback héading 🚀')] },
                paragraph(
                    text('Hi '),
                    { type: 'variable', attrs: { expression: 'person.properties.name', fallback: 'there' } },
                    text(' read '),
                    {
                        type: 'text',
                        text: 'the docs',
                        marks: [{ type: 'link', attrs: { href: 'https://example.com/docs' } }],
                    }
                ),
                {
                    type: 'bulletList',
                    content: [
                        { type: 'listItem', content: [paragraph(text('First point'))] },
                        { type: 'listItem', content: [paragraph(text('Second point'))] },
                    ],
                },
                {
                    type: 'emailImage',
                    attrs: {
                        src: 'https://example.com/a.png',
                        alt: 'An image',
                        href: 'https://example.com/image',
                        emailStyle: { width: 101 },
                    },
                },
                {
                    type: 'emailButton',
                    attrs: {
                        href: 'https://example.com/start',
                        emailVisibility: { hideMobile: true },
                    },
                    content: [text('Get started')],
                },
                { type: 'horizontalRule' },
                { type: 'emailSpacer', attrs: { height: 16 } },
                { type: 'emailSpacer', attrs: { height: 20, backgroundColor: '#123456' } },
                {
                    type: 'emailColumns',
                    attrs: {
                        emailStyle: { backgroundColor: '#ffeecc' },
                        emailVisibility: {
                            condition: { label: 'Trial', before: '{% if trial %}', after: '{% endif %}' },
                            hideDesktop: true,
                        },
                    },
                    content: [
                        { type: 'emailColumn', attrs: { ratio: 1 }, content: [paragraph(text('Left column'))] },
                        { type: 'emailColumn', attrs: { ratio: 1 }, content: [paragraph(text('Right column'))] },
                    ],
                },
                { type: 'emailHtml', attrs: { html: '<p>Custom markup</p>' } },
            ],
        }

        const back = unlayerToEmailDocument(emailDocumentToUnlayer(doc)).document?.doc
        const json = JSON.stringify(back)

        expect(back?.content?.map((node) => node.type)).toEqual([
            'heading',
            'paragraph',
            'bulletList',
            'emailImage',
            'emailButton',
            'horizontalRule',
            'emailSpacer',
            'emailSpacer',
            'emailColumns',
            'emailHtml',
        ])
        expect(back?.attrs?.page.bodyBackgroundColor).toEqual('#fafafa')
        expect(back?.content?.[6].attrs).toEqual({ height: 16 })
        expect(back?.content?.[7].attrs).toEqual({ height: 20, backgroundColor: '#123456' })
        expect(back?.content?.[8].attrs?.emailStyle.backgroundColor).toEqual('#ffeecc')
        expect(back?.content?.[0].attrs?.emailStyle.padding).toEqual({ top: 32, right: 24, bottom: 8, left: 24 })
        expect(back?.content?.[3].attrs?.emailStyle.width).toEqual(101)
        expect(back?.content?.[4].attrs?.emailVisibility).toEqual({ hideMobile: true })
        expect(back?.content?.[8].attrs?.emailVisibility).toEqual(doc.content[8].attrs?.emailVisibility)
        expect(back?.attrs?.page.backgroundImage).toMatchObject({
            url: 'https://example.com/bg.png',
            repeat: true,
            size: 'cover',
        })
        for (const expected of [
            'Rollback héading 🚀',
            'person.properties.name',
            'https://example.com/docs',
            'Second point',
            'https://example.com/a.png',
            'https://example.com/image',
            'Get started',
            'https://example.com/start',
            'Right column',
            'Custom markup',
        ]) {
            expect(json).toContain(expected)
        }
    })
})
