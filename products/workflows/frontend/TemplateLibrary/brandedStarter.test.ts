import { buildBrandedStarter } from './brandedStarter'

type Block = { type: string; slug?: string; values: Record<string, unknown> }

describe('branded starter', () => {
    it('creates an editable ordinary template with fixed readable colors and the unsubscribe block', () => {
        const template = buildBrandedStarter({ name: 'Juniper Studio', primaryColor: '#ffd400' })
        const design = template.content.email.design!
        const blocks = design.body.rows.flatMap((row: { columns: { contents: Block[] }[] }) =>
            row.columns.flatMap((column) => column.contents)
        )
        expect(template).toMatchObject({
            id: 'new',
            name: 'Juniper Studio starter template',
            content: { templating: 'liquid', email: { subject: 'Hello from Juniper Studio' } },
        })
        expect(design.body.values).toMatchObject({
            backgroundColor: '#f5f5f5',
            textColor: '#222222',
            fontFamily: { value: 'arial,helvetica,sans-serif' },
        })
        expect(blocks.find((block: Block) => block.type === 'button')?.values.buttonColors).toMatchObject({
            backgroundColor: '#ffd400',
            color: '#000000',
        })
        expect(
            blocks.find((block: Block) => block.slug === 'unsubscribe_link')?.values.unsubscribe_link_content
        ).toContain('{{ unsubscribe_url }}')
        expect(blocks.some((block: Block) => block.type === 'image')).toBe(false)
    })
    it.each([
        ['#111111', '#ffffff'],
        ['#1d4aff', '#ffffff'],
        ['#0b6e4f', '#ffffff'],
        ['#ffd400', '#000000'],
        ['#ff8800', '#000000'],
        ['#f5f5f5', '#000000'],
    ])('uses readable button text for %s', (primaryColor, expected) => {
        const design = buildBrandedStarter({ name: 'Juniper', primaryColor }).content.email.design!
        const button = design.body.rows[1].columns[0].contents.find((block: Block) => block.type === 'button')!
        expect(button.values.buttonColors).toMatchObject({ color: expected, hoverColor: expected })
    })

    it('treats HTML and Liquid in a name as content and retains a selected logo', () => {
        const template = buildBrandedStarter({
            name: '<img onerror="alert(1)"> {{ person.properties.email }} {% if true %}',
            primaryColor: '#1d4aff',
            logoUrl: 'https://example.com/logo.png',
        })
        expect(template.content.email.subject).not.toMatch(/{{|{%/)
        const design = template.content.email.design!
        const footer = design.body.rows[2].columns[0].contents[0].values.unsubscribe_link_content
        expect(footer).toContain('&lt;img onerror=&quot;alert(1)&quot;&gt;')
        expect(footer).not.toContain('<img')
        expect(footer).not.toContain('{{ person.properties.email }}')
        expect(design.body.rows[0].columns[0].contents[0].values.src).toMatchObject({
            url: 'https://example.com/logo.png',
        })
    })

    it('escapes a name in the heading that replaces a missing logo', () => {
        const design = buildBrandedStarter({
            name: '<img onerror="alert(1)"> {{ person.properties.email }}',
            primaryColor: '#1d4aff',
        }).content.email.design!
        const heading = design.body.rows[0].columns[0].contents[0]
        expect(heading).toMatchObject({
            type: 'heading',
            values: { text: '&lt;img onerror=&quot;alert(1)&quot;&gt;  person.properties.email' },
        })
    })
})
