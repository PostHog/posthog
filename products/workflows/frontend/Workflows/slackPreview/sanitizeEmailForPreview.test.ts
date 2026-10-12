import { sanitizeEmailForPreview } from './sanitizeEmailForPreview'

describe('sanitizeEmailForPreview', () => {
    it('removes content that would load other documents into the capture, and keeps the email itself', () => {
        const emailDocument = sanitizeEmailForPreview(
            `<html><head><base href="https://example.com/"><meta http-equiv="refresh" content="0;url=/api/users/@me/"></head>
            <body><p>Hello</p><img src="https://example.com/banner.png">
            <iframe src="/api/users/@me/"></iframe><object data="/api/users/@me/"></object><embed src="/x">
            <frameset><frame src="/api/users/@me/"></frameset><script>alert(1)</script>
            <video src="/api/exports/1/content" poster="/api/exports/2/content"><source src="/api/exports/3/content"></video>
            <audio src="/api/exports/4/content"></audio></body></html>`
        )

        expect(
            emailDocument.querySelectorAll('iframe, object, embed, frame, frameset, video, audio, source, script, base')
                .length
        ).toBe(0)
        expect(emailDocument.querySelector('meta[http-equiv="refresh"]')).toBeNull()
        expect(emailDocument.body.textContent).toContain('Hello')
        expect(emailDocument.images).toHaveLength(1)
        expect(
            emailDocument.head.querySelector('meta[http-equiv="Content-Security-Policy"]')?.getAttribute('content')
        ).toContain("frame-src 'none'")
    })
})
