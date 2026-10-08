import { withRemoteResourcesBlocked } from './suggestionEmailPreview'

const CSP = 'Content-Security-Policy'

describe('withRemoteResourcesBlocked', () => {
    it.each([
        [
            'a full document',
            '<!DOCTYPE html><html><head><title>Hi</title></head><body><img src="https://example.com/p.png"></body></html>',
        ],
        ['a document without a head', '<html lang="en"><body><img src="https://example.com/p.png"></body></html>'],
        ['a fragment', '<p>Hi</p><img src="https://example.com/p.png">'],
        ['a fragment after a doctype', '<!DOCTYPE html><p>Hi</p><img src="https://example.com/p.png">'],
    ])('puts the policy where the browser applies it, in %s', (_name, html) => {
        const doc = new DOMParser().parseFromString(withRemoteResourcesBlocked(html), 'text/html')

        const policy = doc.head.querySelector(`meta[http-equiv="${CSP}"]`)
        expect(policy?.getAttribute('content')).toContain("default-src 'none'")
        expect(doc.compatMode).toBe(html.toLowerCase().startsWith('<!doctype') ? 'CSS1Compat' : 'BackCompat')
        expect(doc.body.querySelector('img')?.getAttribute('src')).toBe('https://example.com/p.png')
    })
})
