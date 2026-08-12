import { createApp } from '../../src/app.js'

describe('hello API', () => {
    it('serves the feature through the configured HTTP application', async () => {
        const service = createApp({ logLevel: 'error' })
        service.state.ready = true

        const response = await service.app.request('/api/hello/Ada')

        expect(response.status).toBe(200)
        expect(await response.json()).toEqual({ greeting: 'Hello, Ada.' })
        expect(response.headers.get('x-request-id')).toBeTruthy()
    })
})
