import { ARTIFACT_HTML_CSP, withStrictCsp } from './artifactHtml'

describe('withStrictCsp', () => {
    test.each([
        [
            'a full document',
            '<!doctype html><html><head><title>x</title></head><body><img src="https://example.com/a.png"></body></html>',
        ],
        ['a head tag inside a comment', '<!-- <head> --><img src="https://example.com/a.png">'],
        ['a head tag inside a title', '<title><head></title><img src="https://example.com/a.png">'],
        ['a head tag inside a script', '<script>"<head>"</script><img src="https://example.com/a.png">'],
        ['a fragment', '<p>Hello</p><img src="https://example.com/a.png">'],
    ])('the policy is the first element of the parsed head for %s', (_, html) => {
        const doc = new DOMParser().parseFromString(withStrictCsp(html), 'text/html')
        const first = doc.head.firstElementChild
        expect(first?.getAttribute('http-equiv')).toBe('Content-Security-Policy')
        expect(first?.getAttribute('content')).toBe(ARTIFACT_HTML_CSP)
    })
})
