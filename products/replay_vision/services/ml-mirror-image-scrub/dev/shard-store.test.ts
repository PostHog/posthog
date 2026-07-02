import { ParquetReader } from '@dsnp/parquetjs'

import { ImageShardStore } from '../src/shard-store.ts'

/** Fake S3Client capturing PutObjectCommand bodies by key. */
function fakeS3(): { s3: any; objects: Map<string, Buffer> } {
    const objects = new Map<string, Buffer>()
    const s3 = {
        send: (cmd: any) => {
            const { Key, Body } = cmd.input
            objects.set(Key, Buffer.isBuffer(Body) ? Body : Buffer.from(Body))
            return Promise.resolve({})
        },
    }
    return { s3, objects }
}

describe('ImageShardStore', () => {
    it('writes a concat shard + parquet index that round-trips to the exact image bytes', async () => {
        const { s3, objects } = fakeS3()
        const store = new ImageShardStore(s3, 'bucket', 'node1')
        const images = [
            { teamId: 42, hash: 'a'.repeat(22), bytes: Buffer.from('first-image') },
            { teamId: 42, hash: 'b'.repeat(22), bytes: Buffer.from('second-image-longer') },
        ]

        const { shard, bytes } = await store.writeTeam(42, images)

        // The shard is the raw concatenation of scrubbed bytes.
        const shardBody = objects.get(shard)!
        expect(shardBody.toString()).toBe('first-imagesecond-image-longer')
        expect(bytes).toBe(shardBody.length)
        expect(shard).toMatch(/^scrubbed-images\/team_id=42\/shards\/node1-\d+-\d+\.bin$/)

        // The index parquet maps each hash -> (shard, offset, length); the range reproduces the bytes.
        const indexKey = [...objects.keys()].find((k) => k.endsWith('.parquet'))!
        expect(indexKey).toMatch(/^scrubbed-images\/team_id=42\/index\/node1-\d+-\d+\.parquet$/)
        const reader = await ParquetReader.openBuffer(objects.get(indexKey)!)
        const cursor = reader.getCursor()
        const rows: any[] = []
        let row
        while ((row = await cursor.next())) {
            rows.push(row)
        }
        await reader.close()

        expect(rows.length).toBe(2)
        for (const img of images) {
            const r = rows.find((x) => x.hash === img.hash)!
            expect(r.shard).toBe(shard)
            const slice = shardBody.subarray(Number(r.offset), Number(r.offset) + Number(r.length))
            expect(slice.toString()).toBe(img.bytes.toString())
        }
    })
})
