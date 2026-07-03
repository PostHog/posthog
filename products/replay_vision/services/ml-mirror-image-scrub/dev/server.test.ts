import { once } from 'node:events'
import type { AddressInfo } from 'node:net'

import { startServer } from '../src/server.ts'

// A real 40x40 PNG so sharp can actually decode + blur it.
const PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAACgAAAAoCAIAAAADnC86AAAACXBIWXMAAAPoAAAD6AG1e1JrAAAAR0lEQVR4nO3YsQkAIAxEUeu//1A3ljvY2DywD0iSR+6svryjcL56mivjlAUyKzNIhMWwGBaHxbAYFodF12IO80QRE770HDddvGtfTNaUfqIAAAAASUVORK5CYII=',
    'base64'
)

describe('image-scrub sidecar server', () => {
    let base: string
    let server: ReturnType<typeof startServer>

    beforeAll(async () => {
        server = startServer(0, 4)
        await once(server, 'listening')
        base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`
    })
    afterAll((done) => {
        server.closeAllConnections() // drop fetch's keep-alive sockets so close() actually resolves
        server.close(() => done())
    })

    it('scrubs posted image bytes into different (blurred) bytes', async () => {
        const res = await fetch(`${base}/scrub`, { method: 'POST', body: PNG })
        expect(res.status).toBe(200)
        const out = Buffer.from(await res.arrayBuffer())
        expect(out.length).toBeGreaterThan(0)
        expect(out.equals(PNG)).toBe(false)
    })

    it('422s on undecodable bytes so the consumer skips them instead of retrying forever', async () => {
        const res = await fetch(`${base}/scrub`, { method: 'POST', body: Buffer.from('not-an-image') })
        expect(res.status).toBe(422)
    })

    it('serves health + metrics', async () => {
        expect((await fetch(`${base}/_health`)).status).toBe(200)
        const metrics = await fetch(`${base}/metrics`)
        expect(metrics.status).toBe(200)
        expect(await metrics.text()).toContain('ml_mirror_image_scrub_scrubbed_total')
    })
})
