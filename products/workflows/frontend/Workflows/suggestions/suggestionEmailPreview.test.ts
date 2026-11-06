import { emailPreviewDocument } from './suggestionEmailPreview'

const PIXEL = '<img src="https://attacker.example/pixel.gif">'

function preview(html: string, loadRemote = false): Document {
    return new DOMParser().parseFromString(emailPreviewDocument(html, { loadRemote }), 'text/html')
}

function policyOf(doc: Document): string | null | undefined {
    return doc.head.firstElementChild?.matches('meta[http-equiv="Content-Security-Policy"]')
        ? doc.head.firstElementChild.getAttribute('content')
        : undefined
}

describe('emailPreviewDocument', () => {
    it.each([
        ['a full document', `<!DOCTYPE html><html><head><title>Hi</title></head><body>${PIXEL}</body></html>`],
        ['a fragment', `<p>Hi</p>${PIXEL}`],
        ['a head inside a comment', `<!-- <head> --><p>Hi</p>${PIXEL}`],
        ['a head inside a quoted attribute', `<head data-note="> ${PIXEL.replace(/"/g, "'")}"><body>${PIXEL}</body>`],
        ['a head inside a title', `<title><head></title>${PIXEL}`],
    ])('blocks remote images in %s, with the policy first in the real head', (_name, html) => {
        const doc = preview(html)

        expect(policyOf(doc)).toContain('img-src data:;')
        expect(doc.head.querySelectorAll('meta[http-equiv]')).toHaveLength(1)
        expect(doc.querySelector('meta[name="referrer"]')?.getAttribute('content')).toBe('no-referrer')
    })

    it.each([
        ['a refresh', '<meta http-equiv="refresh" content="0;url=https://attacker.example/">'],
        ['a looser policy of its own', `<meta http-equiv="Content-Security-Policy" content="img-src *">`],
        ['a base that repoints links', '<base href="https://attacker.example/">'],
        [
            'a nested frame with its own refresh',
            `<iframe srcdoc="<meta http-equiv='refresh' content='0;url=https://attacker.example/'>"></iframe>`,
        ],
        [
            'an embedded object',
            '<object data="https://attacker.example/x"></object><embed src="https://attacker.example/y">',
        ],
    ])('drops %s from the email, even with remote images loaded', (_name, tag) => {
        const doc = preview(`<html><head>${tag}</head><body><p>Hi</p>${tag}</body></html>`, true)

        expect(doc.querySelectorAll('meta[http-equiv]')).toHaveLength(1)
        expect(doc.querySelectorAll('base, iframe, object, embed')).toHaveLength(0)
        expect(policyOf(doc)).toContain('img-src data: https:')
    })

    it.each([
        [
            'the XHTML transitional doctype emails use',
            '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd"><html><body><p>Hi</p></body></html>',
            'CSS1Compat',
        ],
        ['no doctype', '<p>Hi</p>', 'BackCompat'],
    ])('keeps the rendering mode of %s', (_name, html, mode) => {
        const original = new DOMParser().parseFromString(html, 'text/html')

        expect(original.compatMode).toBe(mode)
        expect(preview(html).compatMode).toBe(mode)
        expect(preview(html).body.textContent).toBe('Hi')
    })
})
