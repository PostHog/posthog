import { inlineSameOriginResources } from './inlineSameOriginResources'

describe('inlineSameOriginResources', () => {
    const fetchMock = jest.fn()

    beforeEach(() => {
        fetchMock.mockReset()
        fetchMock.mockImplementation((url: string) =>
            Promise.resolve(
                url.includes('/api/')
                    ? { ok: false, blob: () => Promise.resolve(new Blob(['{}'], { type: 'application/json' })) }
                    : { ok: true, blob: () => Promise.resolve(new Blob(['png-bytes'], { type: 'image/png' })) }
            )
        )
        global.fetch = fetchMock
    })

    it('loads same-origin images and css urls without the session, and blanks what needs it', async () => {
        const emailDocument = new DOMParser().parseFromString(
            `<html><head><style>.hero { background: url('/uploaded_media/hero.png') no-repeat; }</style></head>
            <body style="background-image: url(/api/projects/1/exports/2/content)">
            <img id="public" src="/uploaded_media/logo.png"><img id="private" src="/api/users/@me/">
            <img id="external" src="https://cdn.example.com/banner.png">
            <svg><image id="svg-image" href="/uploaded_media/icon.png"></image></svg></body></html>`,
            'text/html'
        )

        await inlineSameOriginResources(emailDocument)

        expect(fetchMock.mock.calls.every(([, init]) => init?.credentials === 'omit')).toBe(true)
        expect(emailDocument.getElementById('public')?.getAttribute('src')).toMatch(/^data:image\/png;base64,/)
        expect(emailDocument.getElementById('private')?.getAttribute('src')).not.toContain('/api/')
        expect(emailDocument.getElementById('external')?.getAttribute('src')).toBe('https://cdn.example.com/banner.png')
        expect(emailDocument.getElementById('svg-image')?.getAttribute('href')).toMatch(/^data:image\/png;base64,/)
        expect(emailDocument.head.innerHTML).toMatch(/background: url\("data:image\/png;base64,[^"]+"\) no-repeat/)
        expect(emailDocument.body.getAttribute('style')).toBe('background-image: none')
    })
})
