import { strToU8, zipSync } from 'fflate'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { clearResourceCache, fetchContextMillResources } from '@/resources/internals'

describe('context-mill archive fetching', () => {
    const zipped = zipSync({ 'manifest.json': strToU8('{"version":"1.0","resources":[]}') })
    const archiveBuffer = new ArrayBuffer(zipped.byteLength)
    new Uint8Array(archiveBuffer).set(zipped)
    const localUrl = 'https://localhost/skills-mcp-resources.zip'

    function okResponse(): Response {
        return new Response(archiveBuffer, { status: 200 })
    }

    beforeEach(() => {
        vi.useFakeTimers()
        clearResourceCache()
    })

    afterEach(() => {
        vi.useRealTimers()
        vi.restoreAllMocks()
    })

    async function fetchWithTimers(): Promise<Awaited<ReturnType<typeof fetchContextMillResources>>> {
        const pending = fetchContextMillResources(localUrl)
        // Advancing timers with no handler attached would surface a rejection as unhandled.
        pending.catch(() => {})
        await vi.runAllTimersAsync()
        return pending
    }

    it.each([
        ['a dropped connection', () => Promise.reject(new TypeError('fetch failed'))],
        ['a 503 from the CDN', () => Promise.resolve(new Response('', { status: 503 }))],
    ])('retries past %s', async (_label, transientFailure) => {
        const fetchSpy = vi
            .spyOn(globalThis, 'fetch')
            .mockImplementationOnce(transientFailure)
            .mockImplementationOnce(transientFailure)
            .mockImplementationOnce(() => Promise.resolve(okResponse()))

        await expect(fetchWithTimers()).resolves.toHaveProperty('manifest.json')
        expect(fetchSpy).toHaveBeenCalledTimes(3)
    })

    it('gives up after the attempt budget', async () => {
        const fetchSpy = vi
            .spyOn(globalThis, 'fetch')
            .mockImplementation(() => Promise.reject(new TypeError('fetch failed')))

        await expect(fetchWithTimers()).rejects.toThrow('fetch failed')
        expect(fetchSpy).toHaveBeenCalledTimes(4)
    })

    it('does not retry a missing release', async () => {
        const fetchSpy = vi
            .spyOn(globalThis, 'fetch')
            .mockImplementation(() => Promise.resolve(new Response('', { status: 404, statusText: 'Not Found' })))

        await expect(fetchWithTimers()).rejects.toThrow('Not Found')
        expect(fetchSpy).toHaveBeenCalledTimes(1)
    })
})
