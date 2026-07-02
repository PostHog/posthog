import { ImageBatcher } from '../src/batcher.ts'
import type { ImageShardStore, ScrubbedImage } from '../src/shard-store.ts'

/** Records writeTeam calls and can be told to fail, standing in for the real S3-backed store. */
class FakeStore {
    writes: Array<{ teamId: number; hashes: string[] }> = []
    fail = false
    writeTeam(teamId: number, images: ScrubbedImage[]): Promise<{ shard: string; bytes: number }> {
        if (this.fail) {
            return Promise.reject(new Error('s3 down'))
        }
        this.writes.push({ teamId, hashes: images.map((i) => i.hash) })
        return Promise.resolve({ shard: `shard-${teamId}`, bytes: images.reduce((n, i) => n + i.bytes.length, 0) })
    }
}

const img = (teamId: number, hash: string, bytes = 10): ScrubbedImage => ({
    teamId,
    hash,
    bytes: Buffer.alloc(bytes),
})

function batcher(
    store: FakeStore,
    overrides: Partial<{ maxImages: number; maxBytes: number; flushIntervalMs: number }> = {}
): ImageBatcher {
    return new ImageBatcher(
        store as unknown as ImageShardStore,
        {
            maxImages: overrides.maxImages ?? 1000,
            maxBytes: overrides.maxBytes ?? 1e9,
            flushIntervalMs: overrides.flushIntervalMs ?? 30_000,
        },
        0
    )
}

describe('ImageBatcher', () => {
    it('flushes on the image-count threshold and groups by team into one shard each', async () => {
        const store = new FakeStore()
        const b = batcher(store, { maxImages: 3 })

        b.add(img(42, 'a'))
        b.add(img(99, 'b'))
        expect(b.shouldFlush(0)).toBe(false) // 2 < 3
        b.add(img(42, 'c'))
        expect(b.shouldFlush(0)).toBe(true) // 3 >= 3

        await b.flush(0)
        expect(store.writes.length).toBe(2) // one shard per team
        expect(store.writes.find((w) => w.teamId === 42)?.hashes).toEqual(['a', 'c'])
        expect(store.writes.find((w) => w.teamId === 99)?.hashes).toEqual(['b'])
        expect(b.size).toBe(0)
    })

    it('flushes on the byte threshold', () => {
        const store = new FakeStore()
        const b = batcher(store, { maxBytes: 100 })
        b.add(img(1, 'a', 60))
        expect(b.shouldFlush(0)).toBe(false)
        b.add(img(1, 'b', 60))
        expect(b.shouldFlush(0)).toBe(true) // 120 >= 100
    })

    it('flushes on the interval only when there is something buffered', () => {
        const store = new FakeStore()
        const b = batcher(store, { flushIntervalMs: 1000 })
        expect(b.shouldFlush(5000)).toBe(false) // empty, no flush
        b.add(img(1, 'a'))
        expect(b.shouldFlush(500)).toBe(false) // not old enough
        expect(b.shouldFlush(1000)).toBe(true) // 1000 - 0 >= 1000
    })

    it('a failed write throws and keeps offsets un-committed; the retried images flush next time', async () => {
        const store = new FakeStore()
        const b = batcher(store)
        b.add(img(1, 'a'))
        b.add(img(1, 'b'))
        store.fail = true
        await expect(b.flush(0)).rejects.toThrow()
        // The snapshot was cleared on flush; those images redeliver from Kafka (offsets weren't committed).
        expect(b.size).toBe(0)
        expect(store.writes.length).toBe(0)

        store.fail = false
        b.add(img(1, 'a')) // redelivered
        b.add(img(1, 'b'))
        await b.flush(0)
        expect(store.writes.map((w) => w.hashes)).toEqual([['a', 'b']])
    })
})
