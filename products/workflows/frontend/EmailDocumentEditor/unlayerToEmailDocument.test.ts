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
        expect(unlayerToEmailDocument(design([content(type, {})]))).toEqual({ document: null, unsupported: [reason] })
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
})
