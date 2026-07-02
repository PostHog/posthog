import { ScrubMetrics } from './metrics.ts'
import { ImageShardStore, ScrubbedImage } from './shard-store.ts'

export interface BatcherOptions {
    maxImages: number
    maxBytes: number
    flushIntervalMs: number
}

/** Buffers scrubbed images and flushes them to shard+index objects; offsets are committed only after a
 *  flush lands, so a failed write replays (at-least-once). */
export class ImageBatcher {
    private buffer: ScrubbedImage[] = []
    private bufferBytes = 0
    private lastFlushMs: number

    constructor(
        private readonly store: ImageShardStore,
        private readonly options: BatcherOptions,
        nowMs: number
    ) {
        this.lastFlushMs = nowMs
    }

    public add(image: ScrubbedImage): void {
        this.buffer.push(image)
        this.bufferBytes += image.bytes.length
    }

    public get size(): number {
        return this.buffer.length
    }

    public shouldFlush(nowMs: number): boolean {
        if (this.buffer.length >= this.options.maxImages || this.bufferBytes >= this.options.maxBytes) {
            return true
        }
        return this.buffer.length > 0 && nowMs - this.lastFlushMs >= this.options.flushIntervalMs
    }

    /** Group the buffered images by team and write one shard + index per team. Snapshots and clears the
     *  buffer up front so concurrent adds aren't dropped; throws if a write fails, and since the caller
     *  then doesn't commit offsets, Kafka redelivers those images (the lost snapshot is safe, uncommitted). */
    public async flush(nowMs: number): Promise<void> {
        this.lastFlushMs = nowMs
        if (this.buffer.length === 0) {
            return
        }
        const batch = this.buffer
        this.buffer = []
        this.bufferBytes = 0

        const byTeam = new Map<number, ScrubbedImage[]>()
        for (const image of batch) {
            const images = byTeam.get(image.teamId)
            if (images) {
                images.push(image)
            } else {
                byTeam.set(image.teamId, [image])
            }
        }
        for (const [teamId, images] of byTeam) {
            const { bytes } = await this.store.writeTeam(teamId, images)
            ScrubMetrics.observeShard(images.length, bytes)
        }
    }
}
