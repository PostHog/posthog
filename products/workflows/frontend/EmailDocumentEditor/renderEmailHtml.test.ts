import type { JSONContent } from '@tiptap/core'

import { resolvePageStyle } from './emailDocument'
import { blockStyleToCanvasCss } from './emailExtensions'
import { renderEmailHtml, renderEmailText, safeEmailDoc, withoutLiquidBetweenRows } from './renderEmailHtml'

function doc(...content: JSONContent[]): JSONContent {
    return { type: 'doc', attrs: { page: {} }, content }
}

const paragraph = (text: string): JSONContent => ({ type: 'paragraph', content: [{ type: 'text', text }] })
const linked = (href: string): JSONContent => ({
    type: 'paragraph',
    content: [{ type: 'text', text: 'link', marks: [{ type: 'link', attrs: { href } }] }],
})

describe('renderEmailHtml', () => {
    it.each([
        { name: 'only an empty line', content: [{ type: 'paragraph' }] },
        { name: 'two empty lines', content: [{ type: 'paragraph' }, { type: 'paragraph' }] },
    ])('renders nothing for $name, so "no content" checks keep working', ({ content }) => {
        expect(renderEmailHtml(doc(...content))).toEqual('')
        expect(renderEmailText(doc(...content))).toEqual('')
    })

    it('escapes copy but leaves Liquid for the send path to read', () => {
        const html = renderEmailHtml(doc(paragraph('a < b & c {{ person.properties.plan | default: "x<y" }}')))

        expect(html).toContain('a &lt; b &amp; c {{ person.properties.plan | default: "x<y" }}')
    })

    it.each([
        { href: 'javascript:alert(1)', expected: null },
        { href: 'data:text/html,x', expected: null },
        { href: 'example.com/a', expected: 'https://example.com/a' },
        { href: '{{ unsubscribe_url }}', expected: '{{ unsubscribe_url }}' },
        { href: 'https://example.com/?a=1&b=2', expected: 'https://example.com/?a=1&amp;b=2' },
    ])('writes the link $href safely', ({ href, expected }) => {
        const html = renderEmailHtml(doc(linked(href)))

        if (expected === null) {
            expect(html).not.toContain('<a ')
        } else {
            expect(html).toContain(`<a href="${expected}"`)
        }
    })

    it('keeps a double quote in a Liquid link from ending the attribute', () => {
        const html = renderEmailHtml(doc(linked(`{{ person.properties["a b"] }}`)))

        expect(html).toContain('href="{{ person.properties[&quot;a b&quot;] }}"')
    })

    it('renders a variable with its fallback, escaping the quote in it', () => {
        const html = renderEmailHtml(
            doc({
                type: 'paragraph',
                content: [{ type: 'variable', attrs: { expression: 'person.properties.name', fallback: "it's you" } }],
            })
        )

        expect(html).toContain(`{{ person.properties.name | default: 'it\\'s you' }}`)
    })

    it('leaves a Liquid tag alone on its line out of the table cells', () => {
        const html = renderEmailHtml(doc(paragraph('{% if a %}'), paragraph('Shown'), paragraph('{% endif %}')))

        expect(html).toMatch(/\{% if a %\}<tr>.*Shown.*<\/tr>\{% endif %\}/s)
        // A variable between the tags is content, so that line is sent.
        const withVariable = renderEmailHtml(
            doc({
                type: 'paragraph',
                content: [
                    { type: 'text', text: '{% if a %}' },
                    { type: 'variable', attrs: { expression: 'person.name', fallback: '' } },
                    { type: 'text', text: '{% endif %}' },
                ],
            })
        )
        expect(withVariable).toContain('{{ person.name }}')
    })

    it('colors a spacer, ignoring a color that could break out of the attribute', () => {
        const spacer = (backgroundColor: string): JSONContent => ({
            type: 'emailSpacer',
            attrs: { height: 8, backgroundColor },
        })

        expect(renderEmailHtml(doc(spacer('#ff0000'), paragraph('x')))).toContain('bgcolor="#ff0000"')
        expect(renderEmailHtml(doc(spacer('red"><script>'), paragraph('x')))).not.toContain('<script>')
    })

    it('drops block style values the editor could not have written, in the email and on the canvas', () => {
        const forged = {
            color: 'red;position:fixed;inset:0',
            fontFamily: 'x;background:url(https://example.com/beacon)',
            textAlign: 'left" onclick="x',
            padding: { top: '1px;background:url(x)' },
            fontSize: 18,
        }
        const html = renderEmailHtml(
            doc({ type: 'paragraph', attrs: { emailStyle: forged }, content: [{ type: 'text', text: 'x' }] })
        )
        const canvas = blockStyleToCanvasCss(forged as any, 'paragraph')

        for (const output of [html, canvas]) {
            expect(output).not.toMatch(/position:fixed|url\(|onclick/)
        }
        expect(canvas).toContain('font-size:18px')
        // The page style goes into the editor's own stylesheet in the app.
        expect(
            resolvePageStyle({ h1Size: '32px}body{background:url(x)}' as any, bodyBackgroundColor: 'red;x' })
        ).toMatchObject({ h1Size: 32, bodyBackgroundColor: '#ffffff' })
    })

    it('cleans every style a saved document carries before the canvas shows it', () => {
        const saved = doc(
            {
                type: 'emailButton',
                attrs: { href: 'https://example.com', emailStyle: { backgroundColor: 'red;position:fixed' } },
                content: [{ type: 'text', text: 'Go' }],
            },
            { type: 'emailSpacer', attrs: { height: 8, backgroundColor: 'red;position:fixed' } },
            paragraph('x')
        )
        saved.content![2].content![0].marks = [
            { type: 'textStyle', attrs: { fontFamily: 'Arial;position:fixed', color: '#123456' } },
        ]

        const clean = JSON.stringify(safeEmailDoc(saved))

        expect(clean).not.toMatch(/;position/)
        expect(clean).toContain('#123456')
    })

    it('starts a numbered list where it started in the old editor, in the html and the plain text', () => {
        const list: JSONContent = {
            type: 'orderedList',
            attrs: { start: 3 },
            content: [{ type: 'listItem', content: [paragraph('Third')] }],
        }

        expect(renderEmailHtml(doc(list))).toContain('<ol start="3"')
        expect(renderEmailText(doc(list))).toContain('3. Third')
    })

    it('leaves out the empty line the editor keeps at the end', () => {
        const withTrailingLine = renderEmailHtml(doc(paragraph('Hi'), { type: 'paragraph' }))

        expect(withTrailingLine).toEqual(renderEmailHtml(doc(paragraph('Hi'))))
    })

    it('sends a whole HTML document on its own exactly as written', () => {
        const own = '<!DOCTYPE html><html><body><p>Mine</p></body></html>'

        expect(renderEmailHtml(doc({ type: 'emailHtml', attrs: { html: own } }))).toEqual(own)
    })

    it('unwraps a whole HTML document that sits next to other blocks', () => {
        const own = '<html><head><style>.x{color:red}</style></head><body><p>Mine</p></body></html>'
        const html = renderEmailHtml(doc({ type: 'emailHtml', attrs: { html: own } }, paragraph('After')))

        expect(html.match(/<body/g)).toHaveLength(1)
        expect(html).toContain('<style>.x{color:red}</style><p>Mine</p>')
    })

    it('restores the font inside columns, because the row around them zeroes it', () => {
        const html = renderEmailHtml(
            doc({
                type: 'emailColumns',
                content: [
                    { type: 'emailColumn', attrs: { ratio: 1 }, content: [paragraph('One')] },
                    {
                        type: 'emailColumn',
                        attrs: { ratio: 2, emailStyle: { backgroundColor: '#111111' } },
                        content: [{ type: 'emailHtml', attrs: { html: 'Two' } }],
                    },
                ],
            })
        )

        expect(html).toContain('font-size:0;line-height:0')
        expect(html.match(/class="ph-col ph-col-gap" style="[^"]*font-size:16px;line-height:150%/g)).toHaveLength(2)
        // Outlook ignores inline-block, and a div's background and padding, so the real table cells carry them.
        expect(html).toContain(
            '<!--[if mso]></td><td width="368" valign="top" bgcolor="#111111" style="padding:0px 0px 0px 8px"><![endif]-->'
        )
    })

    it.each([
        {
            name: 'no body border',
            page: {},
            image: { naturalWidth: 2000 },
            expected: ['width="552" style', 'width:100%'],
        },
        {
            name: 'a body border, which takes room inside the body',
            page: { bodyBorderWidth: 2 },
            image: { naturalWidth: 2000 },
            expected: ['width="548" style'],
        },
        {
            name: 'a height for Outlook and a share of the width on phones once resized',
            page: {},
            image: { naturalWidth: 400, naturalHeight: 200, emailStyle: { width: 200 } },
            expected: ['width="200" height="100"', 'width:36.2%;max-width:200px'],
        },
    ])(
        'caps an image at the space it has and gives it a pixel width for Outlook, with $name',
        ({ page, image, expected }) => {
            const html = renderEmailHtml({
                ...doc({ type: 'emailImage', attrs: { src: 'https://example.com/a.png', alt: 'A "b"', ...image } }),
                attrs: { page },
            })

            for (const part of expected) {
                expect(html).toContain(part)
            }
            expect(html).toContain('alt="A &quot;b&quot;"')
        }
    )

    it('writes plain text with links, buttons and separate lines from an HTML block', () => {
        const text = renderEmailText(
            doc(
                paragraph('Hi'),
                {
                    type: 'emailButton',
                    attrs: { href: 'https://example.com' },
                    content: [{ type: 'text', text: 'Go' }],
                },
                { type: 'emailHtml', attrs: { html: '<table><tr><td>One</td></tr><tr><td>Two</td></tr></table>' } },
                {
                    type: 'emailColumns',
                    content: [
                        {
                            type: 'emailColumn',
                            content: [
                                {
                                    ...paragraph('Paid only'),
                                    attrs: {
                                        emailVisibility: {
                                            condition: { before: '{% if paid %}', after: '{% endif %}' },
                                        },
                                    },
                                },
                            ],
                        },
                    ],
                }
            )
        )

        expect(text).toEqual('Hi\n\nGo: https://example.com\n\nOne\nTwo\n\n{% if paid %}Paid only{% endif %}')
        expect(
            renderEmailText(
                doc({
                    type: 'emailHtml',
                    attrs: {
                        html: '<table>{% if vip %}<tr><td>Private</td></tr>{% endif %}<tr><td>All</td></tr></table>',
                    },
                })
            )
        ).toEqual('{% if vip %}Private\n{% endif %}All')
        expect(
            renderEmailText(
                doc({
                    type: 'emailHtml',
                    attrs: {
                        html: '{% if vip %}<!DOCTYPE html><html><body><p>Private</p></body></html>{% endif %}',
                    },
                })
            )
        ).toEqual('{% if vip %}Private\n{% endif %}')
        expect(
            renderEmailText(
                doc({
                    type: 'emailHtml',
                    attrs: {
                        html: '{% if vip %}<html><head><title>A</title></head><body><p>Private</p></body></html>{% else %}<html><body><p>Public</p></body></html>{% endif %}',
                    },
                })
            )
        ).toEqual('{% if vip %}Private\n{% else %}Public\n{% endif %}')
    })

    it('keeps text between Liquid tags in its place, and lets a tag alone on its line sit between rows', () => {
        const paragraph = (text: string): Record<string, any> => ({
            type: 'paragraph',
            content: [{ type: 'text', text }],
        })
        const html = renderEmailHtml({
            type: 'doc',
            content: [
                paragraph('{% if a %}Inline{% endif %}'),
                paragraph('{% for x in y %}'),
                paragraph('Row'),
                paragraph('{% endfor %}'),
            ],
        })
        expect(html).toMatch(/<p [^>]*>\{% if a %\}Inline\{% endif %\}<\/p>/)
        expect(html).toMatch(/<\/tr>\{% for x in y %\}<tr>/)
        expect(withoutLiquidBetweenRows(html)).not.toContain('{% for')
        expect(withoutLiquidBetweenRows(html)).toContain('{% if a %}')
    })

    it('wraps a block only some people see in its condition, hides it by screen size, and changes a button on hover', () => {
        const visible = (emailVisibility: Record<string, any>, block: JSONContent): JSONContent => ({
            ...block,
            attrs: { ...block.attrs, emailVisibility },
        })
        const html = renderEmailHtml(
            doc(
                visible({ condition: { before: '{% if paid %}', after: '{% endif %}' } }, paragraph('Paid only')),
                visible({ hideDesktop: true }, paragraph('Phones only')),
                visible(
                    { hideMobile: true },
                    {
                        type: 'emailButton',
                        attrs: {
                            href: 'https://example.com',
                            emailStyle: { backgroundColor: '#111111', hoverBackgroundColor: '#333333' },
                        },
                        content: [{ type: 'text', text: 'Go' }],
                    }
                )
            )
        )

        expect(html).toMatch(/\{% if paid %\}<tr><td[^>]*><p[^>]*>Paid only<\/p><\/td><\/tr>\{% endif %\}/)
        expect(html).toMatch(
            /<!--\[if !mso\]><!--><tr class="ph-hide-desktop">.*Phones only.*?<\/tr><!--<!\[endif\]-->/
        )
        expect(html).toContain('<tr class="ph-hide-mobile">')
        expect(html).toContain('.ph-hide-desktop { max-height: 0px; overflow: hidden; display: none !important; }')
        expect(html).toContain('.ph-button-1:hover { background-color: #333333 !important; }')
        expect(html).toContain('<td class="ph-button-1"')
        expect(renderEmailHtml(doc(paragraph('Everyone')))).not.toContain('ph-hide')
    })

    it('leaves out a button with no label and adds the preview text and font stylesheet', () => {
        const html = renderEmailHtml({
            type: 'doc',
            attrs: { page: { previewText: 'Peek', fontUrl: 'https://fonts.example.com/a.css' } },
            content: [
                { type: 'emailButton', attrs: { href: 'https://example.com' } },
                { type: 'paragraph', content: [{ type: 'text', text: 'Body' }] },
            ],
        })
        expect(html).not.toContain('https://example.com"')
        expect(html).toContain('>Peek</div>')
        expect(html).toContain('<link rel="stylesheet" href="https://fonts.example.com/a.css"')
    })
})
