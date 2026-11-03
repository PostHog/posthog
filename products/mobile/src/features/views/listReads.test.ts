import { ApiError } from '@/api/client'

import { listRead, retryListRead } from './listReads'
import { viewsQueue } from './refreshQueue'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)

describe('views list reads', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        viewsQueue.reset()
    })

    afterEach(() => {
        viewsQueue.reset()
        jest.useRealTimers()
    })

    test('a 429 is not retried and holds the next read of its family for Retry-After', async () => {
        const throttled = new ApiError(429, {}, { get: () => '30' } as unknown as Headers)
        const read = jest.fn().mockRejectedValueOnce(throttled).mockResolvedValue('pins')

        await expect(listRead('dashboards', undefined, read)).rejects.toBe(throttled)
        expect(retryListRead(0, throttled)).toBe(false)

        const next = listRead('dashboards', undefined, read)
        await jest.advanceTimersByTimeAsync(29_000)
        expect(read).toHaveBeenCalledTimes(1)
        await jest.advanceTimersByTimeAsync(1_000)
        await expect(next).resolves.toBe('pins')
        expect(read).toHaveBeenCalledTimes(2)
    })
})
