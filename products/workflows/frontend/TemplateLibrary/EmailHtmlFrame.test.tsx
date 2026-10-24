import { cleanup, render } from '@testing-library/react'

import { EmailHtmlFrame } from './EmailHtmlFrame'

describe('EmailHtmlFrame', () => {
    afterEach(() => cleanup())

    function renderedDocument(html: string): Document {
        const { container } = render(<EmailHtmlFrame html={html} />)
        return new DOMParser().parseFromString(
            container.querySelector('iframe')?.getAttribute('srcdoc') ?? '',
            'text/html'
        )
    }

    it.each([
        ['a link without a target', '<p><a href="https://example.com">Go</a></p>'],
        ['a link that targets the frame itself', '<p><a href="https://example.com" target="_self">Go</a></p>'],
        [
            'a link in a full document',
            '<!DOCTYPE html><html><head><title>Hi</title></head><body><a href="https://example.com" target="_top">Go</a></body></html>',
        ],
    ])('opens %s in a new tab instead of the preview', (_case, html) => {
        const link = renderedDocument(html).querySelector('a')

        expect(link?.getAttribute('target')).toEqual('_blank')
        expect(link?.textContent).toEqual('Go')
    })

    it('keeps the doctype, so the email renders in the same mode', () => {
        const html =
            '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd"><html><body><p>Hi</p></body></html>'
        const { container } = render(<EmailHtmlFrame html={html} />)

        expect(container.querySelector('iframe')?.getAttribute('srcdoc')).toMatch(
            /^<!DOCTYPE html PUBLIC "-\/\/W3C\/\/DTD XHTML 1\.0 Transitional\/\/EN" "http:\/\/www\.w3\.org\/TR\/xhtml1\/DTD\/xhtml1-transitional\.dtd">/
        )
    })

    it('lets links open a new tab but never runs scripts', () => {
        const { container } = render(<EmailHtmlFrame html="<p>Hi</p>" />)
        const sandbox = container.querySelector('iframe')?.getAttribute('sandbox')?.split(' ')

        expect(sandbox).toEqual(expect.arrayContaining(['allow-popups', 'allow-popups-to-escape-sandbox']))
        expect(sandbox).not.toContain('allow-scripts')
    })
})
