import { PutObjectCommand } from '@aws-sdk/client-s3'
import { randomUUID } from 'crypto'
import pino from 'pino'
import { s3Client } from '../utils/s3'
import { IncomingRecordingMessage } from '../types'
import { config } from '../config'
import { convertToPersitedMessage } from './utils'
import { writeFileSync, mkdirSync, createReadStream } from 'node:fs'
import { appendFile } from 'node:fs/promises'
import path from 'path'

// The buffer is a list of messages grouped
type SessionBuffer = {
    id: string
    count: number
    size: number
    createdAt: Date
    file: string
}

const logger = pino({ name: 'SessionManager', level: process.env.LOG_LEVEL || 'info' })

export class SessionManager {
    chunks: Map<string, IncomingRecordingMessage[]> = new Map()
    buffer: SessionBuffer
    flushBuffer?: SessionBuffer

    constructor(
        public readonly teamId: number,
        public readonly sessionId: string,
        private readonly onFinish: () => void
    ) {
        this.createBuffer()
    }

    public async add(message: IncomingRecordingMessage): Promise<void> {
        if (message.chunk_count === 1) {
            await this.addToBuffer(message)
        } else {
            this.addToChunks(message)
        }

        const capacity = this.buffer.size / (config.sessions.maxEventGroupKb * 1024)
        logger.info(
            `Buffer ${this.sessionId}:: capacity: ${(capacity * 100).toFixed(2)}% count: ${
                this.buffer.count
            } ${Math.round(this.buffer.size / 1024)}KB chunks: ${this.chunks.size})`
        )

        const shouldFlush =
            capacity > 1 ||
            Date.now() - this.buffer.createdAt.getTime() >= config.sessions.maxEventGroupAgeSeconds * 1000

        if (shouldFlush) {
            logger.info(`Flushing buffer ${this.sessionId}...`)
            await this.flush()
        }
    }

    /**
     * Flushing takes the current buffered file and moves it to the flush buffer
     * We then attempt to write the events to S3 and if successful, we clear the flush buffer
     */
    public async flush(): Promise<void> {
        if (this.flushBuffer) {
            logger.warn("Flush called but we're already flushing")
            return
        }
        // We move the buffer to the flush buffer and create a new buffer so that we can safely write the buffer to disk
        this.flushBuffer = this.buffer
        this.createBuffer()

        try {
            const baseKey = `${config.s3.sessionRecordingFolder}/team_id/${this.teamId}/session_id/${this.sessionId}`
            const dataKey = `${baseKey}/data/${this.flushBuffer.createdAt.getTime()}` // TODO: Change to be based on events times
            const fileStream = createReadStream(this.flushBuffer.file)

            await s3Client.send(
                new PutObjectCommand({
                    Bucket: config.s3.bucket,
                    Key: dataKey,
                    Body: fileStream,
                })
            )

            // TODO: Increment file count and size metric
        } catch (error) {
            // TODO: If we fail to write to S3 we should be do something about it
            logger.error(error)
        } finally {
            this.flushBuffer = undefined

            if (this.buffer.count === 0 && this.chunks.size === 0) {
                // TODO: We should probably time out on chunks?
                this.onFinish()
            }
        }
    }

    private createBuffer(): void {
        const id = randomUUID()
        this.buffer = {
            id,
            count: 0,
            size: 0,
            createdAt: new Date(),
            file: path.join(config.sessions.directory, `${this.teamId}.${this.sessionId}.${id}.json`),
        }

        // NOTE: We should move this to do once on startup
        mkdirSync(config.sessions.directory, { recursive: true })
        // NOTE: We may want to figure out how to safely do this async
        writeFileSync(this.buffer.file, '', 'utf-8')
    }

    /**
     * Full messages (all chunks) are added to the buffer directly
     */
    private async addToBuffer(message: IncomingRecordingMessage): Promise<void> {
        await appendFile(this.buffer.file, JSON.stringify(convertToPersitedMessage(message)) + '\n', 'utf-8')

        // this.buffer.fileData.push(convertToPersitedMessage(message))
        this.buffer.count += 1
        this.buffer.size += Buffer.byteLength(message.data)
    }

    /**
     * Chunked messages are added to the chunks map
     * Once all chunks are received, the message is added to the buffer
     *
     */
    private addToChunks(message: IncomingRecordingMessage): void {
        // If it is a chunked message we add to the collected chunks
        let chunks: IncomingRecordingMessage[] = []

        if (!this.chunks.has(message.chunk_id)) {
            this.chunks.set(message.chunk_id, chunks)
        } else {
            chunks = this.chunks.get(message.chunk_id)
        }

        chunks.push(message)

        if (chunks.length === message.chunk_count) {
            // If we have all the chunks, we can add the message to the buffer
            this.addToBuffer({
                ...message,
                data: chunks
                    .sort((a, b) => a.chunk_index - b.chunk_index)
                    .map((c) => c.data)
                    .join(''),
            })
            this.chunks.delete(message.chunk_id)
        }
    }
}
