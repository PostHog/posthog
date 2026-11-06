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
        { type: 'menu', reason: 'menus' },
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

    it('turns Liquid in copy into variables, keeping its fallback and the marks around it', () => {
        const { document } = unlayerToEmailDocument(
            design([
                content('text', { text: `<p>Hi <strong>{{ person.properties.name | default: 'you' }}</strong></p>` }),
            ])
        )

        expect(document?.doc.content?.[0].content?.[1]).toMatchObject({
            type: 'variable',
            attrs: { expression: 'person.properties.name', fallback: 'you' },
            marks: [{ type: 'bold' }],
        })
    })

    it("spreads a text block's padding over its paragraphs without doubling the gaps between them", () => {
        const { document } = unlayerToEmailDocument(
            design([content('text', { text: '<p>One</p><p>Two</p>', containerPadding: '10px' })])
        )

        expect(document?.doc.content?.map((node) => node.attrs?.emailStyle.padding)).toEqual([
            { top: 10, right: 10, bottom: 0, left: 10 },
            { top: 0, right: 10, bottom: 10, left: 10 },
        ])
    })

    it('keeps a social footer looking the same, as an HTML block', () => {
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
            'a border on one side of a button',
            content('button', { border: { borderTopWidth: '2px', borderTopStyle: 'solid' } }),
            'buttons with a border on only some sides',
        ],
        ['right-to-left text', content('text', { text: '<p dir="rtl">x</p>' }), 'right-to-left text'],
    ])('refuses %s rather than dropping it', (_name, block, reason) => {
        const conversion = unlayerToEmailDocument(design([block]))
        expect(conversion.document).toBeNull()
        expect(conversion.unsupported).toContain(reason)
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
        expect(conversion.notKept).toEqual(['button colors on hover'])
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

    it('keeps the old editor defaults: regular headings, percentages from bare line heights, and a 500px body', () => {
        const doc = unlayerToEmailDocument(
            design([content('heading', { text: 'Title' }), content('text', { text: '<p>Body</p>', lineHeight: 1.6 })])
        ).document?.doc as Record<string, any>

        expect(doc.content[0].attrs.emailStyle.fontWeight).toBe(400)
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

        const [kept] = unlayerToEmailDocument(
            design([content('text', { text: '<p style="border-top: 1px solid red;">Ruled</p>' })])
        ).document?.doc.content as Record<string, any>[]
        expect(kept.type).toBe('emailHtml')
        expect(kept.attrs?.html).toContain('border-top: 1px solid red')
    })
})
