import { Page, expect } from '@playwright/test'

interface Connection {
    url: string
    cursor: string | null
    ids: string[]
    frames: string[]
}

declare global {
    interface Window {
        aiE2eTransport: { connections: Connection[]; disconnect: () => void }
    }
}

export async function observeLiveTransport(page: Page): Promise<void> {
    await page.addInitScript(() => {
        const fetch = window.fetch.bind(window)
        window.aiE2eTransport = {
            connections: [],
            disconnect: () => {
                throw new Error('No live stream')
            },
        }
        window.fetch = async (input, init) => {
            const response = await fetch(input, init)
            const url = input instanceof Request ? input.url : String(input)
            if (!/\/runs\/[^/]+\/stream\/?(?:\?|$)/.test(url) || !response.ok || !response.body) {
                return response
            }
            const connection: Connection = {
                url,
                cursor: new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined)).get(
                    'Last-Event-ID'
                ),
                ids: [],
                frames: [],
            }
            window.aiE2eTransport.connections.push(connection)
            const reader = response.body.getReader()
            const decoder = new TextDecoder()
            let buffer = ''
            let disconnected = false
            const body = new ReadableStream<Uint8Array>({
                start(controller) {
                    window.aiE2eTransport.disconnect = () => {
                        disconnected = true
                        controller.error(new TypeError('Synthetic connection loss'))
                        void reader.cancel()
                    }
                },
                async pull(controller) {
                    try {
                        const { done, value } = await reader.read()
                        if (disconnected) {
                            return
                        }
                        if (done) {
                            controller.close()
                            return
                        }
                        buffer += decoder.decode(value, { stream: true })
                        const frames = buffer.split(/\r?\n\r?\n/)
                        buffer = frames.pop() ?? ''
                        for (const frame of frames) {
                            connection.frames.push(frame)
                            const id = /^id: *(.+)$/m.exec(frame)?.[1]
                            if (id) {
                                connection.ids.push(id)
                            }
                        }
                        controller.enqueue(value)
                    } catch (error) {
                        if (!disconnected) {
                            controller.error(error)
                        }
                    }
                },
                cancel: () => reader.cancel(),
            })
            return new Response(body, { status: response.status, headers: response.headers })
        }
    })
}

export async function disconnectLiveTransport(page: Page): Promise<void> {
    await expect
        .poll(() => page.evaluate(() => window.aiE2eTransport.connections.at(-1)?.ids.length ?? 0))
        .toBeGreaterThan(0)
    const before = await page.evaluate(() => {
        const connections = window.aiE2eTransport.connections
        const last = connections.at(-1)!
        window.aiE2eTransport.disconnect()
        return { count: connections.length, id: last.ids.at(-1), url: last.url }
    })
    await expect.poll(() => page.evaluate(() => window.aiE2eTransport.connections.length)).toBe(before.count + 1)
    const next = await page.evaluate(() => window.aiE2eTransport.connections.at(-1))
    expect(next?.cursor).toBe(before.id)
    expect(new URL(next!.url, page.url()).pathname.replace(/\/$/, '')).toBe(
        new URL(before.url, page.url()).pathname.replace(/\/$/, '')
    )
}
