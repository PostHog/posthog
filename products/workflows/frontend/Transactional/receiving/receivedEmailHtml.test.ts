import { buildReceivedEmailDocument, hasRemoteImages } from './receivedEmailHtml'

describe('receivedEmailHtml', () => {
    it.each([
        ['blocks', false, 'img-src data:;'],
        ['allows', true, 'img-src data: https:;'],
    ])('%s remote images in the policy', (_, allowRemoteImages, expected) => {
        expect(buildReceivedEmailDocument('<p>hi</p>', { allowRemoteImages })).toContain(expected)
    })

    it.each([
        ['a refresh', '<meta http-equiv="refresh" content="0;url=https://tracker.example/x">', 'tracker.example'],
        ['a prefetch', '<link rel="dns-prefetch" href="https://tracker.example">', 'tracker.example'],
        ['a base URL', '<base href="https://tracker.example/">', 'tracker.example'],
    ])('drops %s that would contact the sender while keeping the content', (_, element, sender) => {
        const document = buildReceivedEmailDocument(`${element}<style>p { color: red }</style><p>Hello</p>`, {
            allowRemoteImages: true,
        })
        expect(document).not.toContain(sender)
        expect(document).toContain('<style>p { color: red }</style>')
        expect(document).toContain('<p>Hello</p>')
    })

    it.each([
        [
            'a refresh hidden by a form and math parser trick',
            '<form><math><mtext></form><form><mglyph><style></math><meta http-equiv="refresh" content="0;url=https://tracker.example/">',
            'tracker.example',
        ],
        [
            'a refresh hidden by a table and math parser trick',
            '<math><mtext><table><mglyph><style><meta http-equiv="refresh" content="0;url=https://tracker.example/">',
            'tracker.example',
        ],
    ])('drops %s', (_, html, sender) => {
        const document = buildReceivedEmailDocument(html, { allowRemoteImages: true })
        expect(document).not.toContain(sender)
        expect(document).not.toContain('refresh')
    })

    it('keeps the attributes of the email body', () => {
        const document = buildReceivedEmailDocument('<body bgcolor="#111111" dir="rtl"><p>مرحبا</p></body>', {
            allowRemoteImages: false,
        })
        expect(document).toContain('<body bgcolor="#111111" dir="rtl">')
    })

    it.each([
        ['<img src="https://tracker.example/p.gif">', true],
        ["<IMG alt=x SRC='//tracker.example/p.gif'>", true],
        ['<div style="background: url(https://tracker.example/p.gif)"></div>', true],
        ['<img src="data:image/png;base64,AAAA">', false],
        ['<p>https://example.com is a link in text</p>', false],
        ['<img alt="x" src = " https://tracker.example/p.gif">', true],
        ["<style>a { background: url( ' //tracker.example/p.gif') }</style>", true],
        ['<img src="data:image/png;base64,AAAA"><img src="https://tracker.example/p.gif">', true],
        ['<img src="data:image/png;base64,AAAA"', false],
        ['<img alt="https://example.com">', false],
        ['<img srcset="https://tracker.example/p.gif 2x">', true],
        ['<picture><source srcset="//tracker.example/p.gif"></picture>', true],
    ])('finds remote images in %s', (html, expected) => {
        expect(hasRemoteImages(html)).toBe(expected)
    })

    it.each([
        ['an unclosed image tag repeated', '<img '.repeat(40000), false],
        ['a url( followed by spaces', `url(${' '.repeat(200000)}`, false],
        ['a src= repeated in one tag', `<img ${'src= '.repeat(40000)}`, false],
    ])('answers %s', (_, html, expected) => {
        expect(hasRemoteImages(html)).toBe(expected)
    })
})
