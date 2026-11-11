import { integrationsGithubRepositoryAccessRetrieve } from 'products/integrations/frontend/generated/api'

import { GithubAccessProbes } from './GithubAccessProbes'

jest.mock('products/integrations/frontend/generated/api', () => ({
    integrationsGithubRepositoryAccessRetrieve: jest.fn(),
}))

describe('GithubAccessProbes', () => {
    const request = jest.mocked(integrationsGithubRepositoryAccessRetrieve)

    beforeEach(() => request.mockReset())
    afterEach(() => {
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    it('shares recent checks while keeping projects, installations, and repositories separate', async () => {
        request.mockResolvedValue({ available: true })
        const now = jest.spyOn(Date, 'now').mockReturnValue(100_000)
        const probes = new GithubAccessProbes()
        const first = probes.acquire('1', 1, 'example/app')
        const second = probes.acquire('1', 1, 'example/app')
        expect(await Promise.all([first.promise, second.promise])).toEqual([true, true])
        first.release()
        second.release()
        expect(await probes.acquire('1', 1, 'example/app').promise).toBe(true)
        expect(request).toHaveBeenCalledTimes(1)
        for (const [project, integration, repository] of [
            ['2', 1, 'example/app'],
            ['1', 2, 'example/app'],
            ['1', 1, 'example/other'],
        ] as const) {
            await probes.acquire(project, integration, repository).promise
        }
        expect(request).toHaveBeenCalledTimes(4)
        now.mockReturnValue(130_001)
        await probes.acquire('1', 1, 'example/app').promise
        expect(request).toHaveBeenCalledTimes(5)
        probes.invalidate('1')
        await probes.acquire('1', 1, 'example/app').promise
        expect(request).toHaveBeenCalledTimes(6)
    })

    it.each(['last reader leaves', 'deadline expires'])('cancels a pending request when its %s', async (cause) => {
        jest.useFakeTimers()
        request.mockImplementation(
            (_project, _integration, _params, options) =>
                new Promise((_resolve, reject) => {
                    options?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
                })
        )
        const probes = new GithubAccessProbes()
        const first = probes.acquire('1', 1, 'example/app')
        const second = probes.acquire('1', 1, 'example/app')
        const signal = request.mock.calls[0][3]!.signal!
        first.release()
        expect(signal.aborted).toBe(false)
        if (cause === 'deadline expires') {
            jest.advanceTimersByTime(30_000)
        } else {
            second.release()
        }
        expect(signal.aborted).toBe(true)
        await expect(second.promise).rejects.toMatchObject({ name: 'AbortError' })
        second.release()
        request.mockResolvedValue({ available: true })
        expect(await probes.acquire('1', 1, 'example/app').promise).toBe(true)
        expect(request).toHaveBeenCalledTimes(2)
        expect(jest.getTimerCount()).toBe(0)
    })

    it('rechecks failed probes instead of caching a temporary error', async () => {
        request.mockRejectedValueOnce(new Error('Unavailable')).mockResolvedValue({ available: false })
        const probes = new GithubAccessProbes()
        await expect(probes.acquire('1', 1).promise).rejects.toThrow('Unavailable')
        expect(await probes.acquire('1', 1).promise).toBe(false)
    })
})
