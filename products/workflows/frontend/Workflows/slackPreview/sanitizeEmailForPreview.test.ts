import { sanitizeEmailForPreview } from './sanitizeEmailForPreview'

describe('sanitizeEmailForPreview', () => {
    it('removes content that would load other documents into the capture, and keeps the email itself', () => {
        const emailDocument = sanitizeEmailForPreview(
            `<html><head><base href="https://example.com/"><meta http-equiv="refresh" content="0;url=/api/users/@me/"></head>
            <body><p>Hello</p><img src="https://example.com/banner.png">
            <iframe src="/api/users/@me/"></iframe><object data="/api/users/@me/"></object><embed src="/x">
            <frameset><frame src="/api/users/@me/"></frameset><script>alert(1)</script></body></html>`
        )

        expect(emailDocument.querySelectorAll('iframe, object, embed, frame, frameset, script, base').length).toBe(0)
        expect(emailDocument.querySelector('meta[http-equiv="refresh"]')).toBeNull()
        expect(emailDocument.body.textContent).toContain('Hello')
        expect(emailDocument.images).toHaveLength(1)
        expect(
            emailDocument.head.querySelector('meta[http-equiv="Content-Security-Policy"]')?.getAttribute('content')
        ).toContain("frame-src 'none'")
    })
})
