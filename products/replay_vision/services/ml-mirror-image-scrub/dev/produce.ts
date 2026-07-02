/* eslint-disable no-console -- CLI logs to stdout */
/**
 * Producer CLI for local end-to-end testing: post an image's raw bytes to the scrub topic under its
 * team-scoped reference, so the consumer (npm run consume) scrubs it to S3.
 *
 *   npm run produce -- <image-path> <team-id>
 *
 * This is a thin test harness. The real routing (tiny/canvas/oversize handled without producing) and
 * Redis dedup live in the ml-mirror producer in nodejs, not here — this just posts one image so you
 * can exercise the consumer.
 */
import { Kafka } from 'kafkajs'
import { readFile } from 'node:fs/promises'

import { ensureTopic } from '../src/clients.ts'
import { loadConfig } from '../src/config.ts'
import { hashImageBytes, imageRef } from '../src/content-ref.ts'

async function main(): Promise<void> {
    const [file, teamStr] = process.argv.slice(2)
    if (!file || !teamStr) {
        console.error('usage: npm run produce -- <image-path> <team-id>')
        process.exit(2)
    }
    const teamId = Number(teamStr)
    const bytes = await readFile(file)
    const ref = imageRef(teamId, hashImageBytes(bytes))

    const cfg = loadConfig()
    const kafka = new Kafka({ clientId: 'ml-mirror-image-scrub-producer', brokers: cfg.kafkaBrokers })
    await ensureTopic(kafka, cfg.topic)
    const producer = kafka.producer()
    await producer.connect()
    try {
        await producer.send({ topic: cfg.topic, acks: -1, messages: [{ key: ref, value: bytes }] })
        console.log(`posted ${ref} (${bytes.length} bytes)`)
    } finally {
        await producer.disconnect()
    }
}

main().catch((e) => {
    console.error(e)
    process.exit(1)
})
