import { buildReceivedEmailDocument, hasRemoteImages } from './receivedEmailHtml'

describe('receivedEmailHtml', () => {
    it.each([
        ['blocks', false, 'img-src data:;'],
        ['allows', true, 'img-src data: https:;'],
    ])('%s remote images in the policy', (_, allowRemoteImages, expected) => {
        expect(buildReceivedEmailDocument('<p>hi</p>', { allowRemoteImages })).toContain(expected)
    })

    it.each([
        ['<img src="https://tracker.example/p.gif">', true],
        ["<IMG alt=x SRC='//tracker.example/p.gif'>", true],
        ['<div style="background: url(https://tracker.example/p.gif)"></div>', true],
        ['<img src="data:image/png;base64,AAAA">', false],
        ['<p>https://example.com is a link in text</p>', false],
    ])('finds remote images in %s', (html, expected) => {
        expect(hasRemoteImages(html)).toBe(expected)
    })
})
