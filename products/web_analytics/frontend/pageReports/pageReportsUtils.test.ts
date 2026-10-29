import { pageKeyForUrl, pageUrlForHost } from './pageReportsUtils'

describe('pageReportsUtils', () => {
    test.each<[string, string, string | null, string]>([
        ['keeps the URL host', 'https://example.com/pricing?ref=nav', null, 'example.com/pricing'],
        [
            'uses the selected host over the URL host',
            'https://example.com/pricing',
            'docs.example.com',
            'docs.example.com/pricing',
        ],
        ['keeps a hostless path hostless', '/pricing', null, '/pricing'],
        ['scopes a hostless path to the selected host', '/pricing', 'example.com', 'example.com/pricing'],
    ])('pageKeyForUrl: %s', (_name, url, selectedHost, expected) => {
        expect(pageKeyForUrl(url, false, [], selectedHost)).toEqual(expected)
    })

    test.each<[string, string, string | null, string]>([
        [
            'keeps the URL without a selected host',
            'https://example.com/pricing?ref=nav',
            null,
            'https://example.com/pricing?ref=nav',
        ],
        [
            'swaps in the selected host',
            'https://example.com/pricing?ref=nav',
            'docs.example.com',
            'https://docs.example.com/pricing?ref=nav',
        ],
        ['adds the selected host to a hostless path', '/pricing', 'example.com', 'https://example.com/pricing'],
    ])('pageUrlForHost: %s', (_name, url, selectedHost, expected) => {
        expect(pageUrlForHost(url, selectedHost)).toEqual(expected)
    })
})
