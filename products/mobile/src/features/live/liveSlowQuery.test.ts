import { readSlowLiveQuery } from './liveSlowQuery'

jest.mock('@/auth/authStore', () => ({ addSessionEndTask: jest.fn() }))

describe('Slow Live query cache', () => {
    it('backs off failures for a minute and isolates projects', async () => {
        await expect(readSlowLiveQuery('a', 0, () => Promise.reject(new Error('offline')))).rejects.toThrow('offline')
        await expect(readSlowLiveQuery('a', 30000, () => Promise.resolve({ results: [] }))).rejects.toThrow('offline')
        await expect(readSlowLiveQuery('b', 30000, () => Promise.resolve({ results: [[1]] }))).resolves.toMatchObject({
            results: [[1]],
        })
        await expect(readSlowLiveQuery('a', 60000, () => Promise.resolve({ results: [[2]] }))).resolves.toMatchObject({
            results: [[2]],
        })
    })

    it('preserves fetch time across remounts and reports refresh failures until recovery', async () => {
        const initial = { results: [[5]] }
        expect(await readSlowLiveQuery('freshness', 0, () => Promise.resolve(initial))).toMatchObject({
            liveFetchedAt: 0,
        })
        expect(await readSlowLiveQuery('freshness', 3500000, () => Promise.resolve({ results: [[99]] }))).toMatchObject(
            {
                results: [[5]],
                liveFetchedAt: 0,
            }
        )
        await expect(
            readSlowLiveQuery('freshness', 3600000, () => Promise.reject(new Error('offline')))
        ).rejects.toThrow('offline')
        expect(await readSlowLiveQuery('freshness', 3660000, () => Promise.resolve({ results: [[6]] }))).toMatchObject({
            results: [[6]],
            liveFetchedAt: 3660000,
        })
    })
})
