import { withLinksInNewTab } from './EmailHtmlFrame'

describe('withLinksInNewTab', () => {
    it.each([
        [
            'a full document, inside its head',
            '<!DOCTYPE html><html><head lang="en"><title>Hi</title></head><body><a href="https://example.com">Go</a></body></html>',
            '<!DOCTYPE html><html><head lang="en"><base target="_blank"><title>Hi</title></head><body><a href="https://example.com">Go</a></body></html>',
        ],
        [
            'a fragment, in front of it',
            '<p><a href="https://example.com">Go</a></p>',
            '<base target="_blank"><p><a href="https://example.com">Go</a></p>',
        ],
        [
            'a document whose header element is not a head',
            '<header>Hi</header>',
            '<base target="_blank"><header>Hi</header>',
        ],
    ])('opens links outside the preview for %s', (_case, html, expected) => {
        expect(withLinksInNewTab(html)).toEqual(expected)
    })
})
