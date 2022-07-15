import { beforeEach, afterEach, expect, it, describe } from 'vitest'
import { Kafka, Partitioners, Producer } from 'kafkajs'
import http from 'http'
import { v4 as uuidv4 } from 'uuid'
import { gzipSync } from 'zlib'

declare module 'vitest' {
    export interface TestContext {
        producer: Producer
    }
}

const RECORDING_EVENTS_TOPIC = 'recording_events'

describe.concurrent('ingester', () => {
    // TODO: add tests for:
    //
    //  * ensuring chunks are complete before committing them
    //  * ensure we seek to first chunk if the offset is already passed it (I
    //    think we might actually get away with that the way we are handling
    //    manually committing the offsets.)

    it('handles one event', async ({ producer }) => {
        const teamId = '1'
        const sessionId = uuidv4()
        const windowId = uuidv4()
        const eventUuid = uuidv4()

        await producer.send({
            topic: RECORDING_EVENTS_TOPIC,
            messages: [
                {
                    partition: 0,
                    headers: {
                        unixTimestamp: '1657682896740',
                        eventId: eventUuid,
                        sessionId: sessionId,
                        windowId: windowId,
                        distinctId: '123',
                        chunkIndex: '0',
                        chunkCount: '1',
                        teamId: '1',
                        eventSource: '1',
                        eventType: '3',
                    },
                    value: `{"uuid": "${eventUuid}", "type": 3, "data": {"source": 1, "positions": [{"x": 829, "y": 154, "id": 367, "timeOffset": 0}]}, "timestamp": 1657682896740}`,
                },
            ],
        })

        const sessionRecording = await waitForSessionRecording(teamId, sessionId, eventUuid)

        expect(sessionRecording.events.length).toBe(1)
    })

    it('handles chunked events', async ({ producer }) => {
        const teamId = '1'
        const sessionId = uuidv4()
        const windowId = uuidv4()
        const eventUuid = uuidv4()

        const fullEventString = `{"uuid": "${eventUuid}", "type": 3, "data": {"source": 1, "positions": [{"x": 829, "y": 154, "id": 367, "timeOffset": 0}]}, "timestamp": 1657682896740}`

        const [first] = await producer.send({
            topic: RECORDING_EVENTS_TOPIC,
            messages: [
                {
                    partition: 0,
                    headers: {
                        unixTimestamp: '1657682896740',
                        eventId: eventUuid,
                        sessionId: sessionId,
                        windowId: windowId,
                        distinctId: '123',
                        chunkIndex: '0',
                        chunkCount: '2',
                        teamId: '1',
                        eventSource: '1',
                        eventType: '3',
                    },
                    value: fullEventString.slice(0, 100),
                },
            ],
        })

        await producer.send({
            topic: RECORDING_EVENTS_TOPIC,
            messages: [
                {
                    partition: 0,
                    headers: {
                        unixTimestamp: '1657682896740',
                        eventId: eventUuid,
                        sessionId: sessionId,
                        windowId: windowId,
                        distinctId: '123',
                        chunkIndex: '1',
                        chunkCount: '2',
                        chunkOffset: first.baseOffset,
                        teamId: '1',
                        eventSource: '1',
                        eventType: '3',
                    },
                    value: fullEventString.slice(100),
                },
            ],
        })

        const sessionRecording = await waitForSessionRecording(teamId, sessionId, eventUuid)

        expect(sessionRecording.events.length).toBe(1)
        expect(sessionRecording.events[0]).toMatchObject(JSON.parse(fullEventString))
    })

    // TODO: Handle this case and re-enable the test
    it.skip('handles duplicate parts of chunked events', async ({ producer }) => {
        const teamId = '1'
        const sessionId = uuidv4()
        const windowId = uuidv4()
        const eventUuid = uuidv4()

        const fullEventString = `{"uuid": "${eventUuid}", "type": 3, "data": {"source": 1, "positions": [{"x": 829, "y": 154, "id": 367, "timeOffset": 0}]}, "timestamp": 1657682896740}`

        const firstEvent = {
            partition: 0,
            headers: {
                unixTimestamp: '1657682896740',
                eventId: eventUuid,
                sessionId: sessionId,
                windowId: windowId,
                distinctId: '123',
                chunkIndex: '0',
                chunkCount: '2',
                teamId: '1',
                eventSource: '1',
                eventType: '3',
            },
            value: fullEventString.slice(0, 100),
        }
        const [first] = await producer.send({
            topic: RECORDING_EVENTS_TOPIC,
            messages: [firstEvent],
        })
        await producer.send({
            topic: RECORDING_EVENTS_TOPIC,
            messages: [firstEvent],
        })

        await producer.send({
            topic: RECORDING_EVENTS_TOPIC,
            messages: [
                {
                    partition: 0,
                    headers: {
                        unixTimestamp: '1657682896740',
                        eventId: eventUuid,
                        sessionId: sessionId,
                        windowId: windowId,
                        distinctId: '123',
                        chunkIndex: '1',
                        chunkCount: '2',
                        chunkOffset: first.baseOffset,
                        teamId: '1',
                        eventSource: '1',
                        eventType: '3',
                    },
                    value: fullEventString.slice(100),
                },
            ],
        })

        const sessionRecording = await waitForSessionRecording(teamId, sessionId, eventUuid)

        expect(sessionRecording.events.length).toBe(1)
        expect(sessionRecording.events[0]).toMatchObject(JSON.parse(fullEventString))
    })

    // TODO: Handle this case and re-enable the test
    it.skip('does not write incomplete events', async ({ producer }) => {
        const teamId = '1'
        const sessionId = uuidv4()
        const windowId = uuidv4()
        const eventUuid = uuidv4()

        const fullEventString = `{"uuid": "${eventUuid}", "type": 3, "data": {"source": 1, "positions": [{"x": 829, "y": 154, "id": 367, "timeOffset": 0}]}, "timestamp": 1657682896740}`

        await producer.send({
            topic: RECORDING_EVENTS_TOPIC,
            messages: [
                {
                    partition: 0,
                    headers: {
                        unixTimestamp: '1657682896740',
                        eventId: eventUuid,
                        sessionId: sessionId,
                        windowId: windowId,
                        distinctId: 'abc123',
                        chunkIndex: '0',
                        chunkCount: '2',
                        teamId: '1',
                        eventSource: '1',
                        eventType: '3',
                    },
                    value: fullEventString.slice(0, 100),
                },
            ],
        })

        const sessionRecording = await waitForSessionRecording(teamId, sessionId, eventUuid)

        expect(sessionRecording.events.length).toBe(0)
    })

    it('handles event larger than the max chunk limit', async ({ producer }) => {
        const teamId = '1'
        const sessionId = uuidv4()
        const windowId = uuidv4()
        const eventUuid = uuidv4()

        await producer.send({
            topic: RECORDING_EVENTS_TOPIC,
            messages: [
                {
                    partition: 0,
                    headers: {
                        unixTimestamp: '1657682896740',
                        eventId: eventUuid,
                        sessionId: sessionId,
                        windowId: windowId,
                        distinctId: 'abc123',
                        chunkIndex: '0',
                        chunkCount: '1',
                        teamId: teamId,
                        eventSource: '1',
                        eventType: '3',
                    },
                    value: `{"uuid": "${eventUuid}", "type": 3, "data": ${JSON.stringify(
                        Array.from(new Array(100000).keys())
                    )}, "timestamp": 1657682896740}`,
                },
            ],
        })

        const sessionRecording = await waitForSessionRecording(teamId, sessionId, eventUuid)

        expect(sessionRecording.events.length).toBe(1)
    })

    it.skip('handles lots of events', async ({ producer }) => {
        const teamId = '1'
        const sessionId = uuidv4()
        const windowId = uuidv4()

        const messages = Array.from(new Array(30).keys()).map((_) => {
            const eventUuid = uuidv4()
            return {
                partition: 0,
                headers: {
                    unixTimestamp: '1657682896740',
                    eventId: eventUuid,
                    sessionId: sessionId,
                    windowId: windowId,
                    distinctId: 'abc123',
                    chunkIndex: '0',
                    chunkCount: '1',
                    teamId: teamId,
                    eventSource: '1',
                    eventType: '3',
                },
                value: `{"uuid": "${eventUuid}", "type": 3, "data": {"source": 1, "positions": [{"x": 829, "y": 154, "id": 367, "timeOffset": 0}]}, "timestamp": 1657682896740}`,
            }
        })

        await producer.send({
            topic: RECORDING_EVENTS_TOPIC,
            messages: messages,
        })

        const sessionRecording = await waitForSessionRecording(
            teamId,
            sessionId,
            messages.slice(-1)[0].headers.eventId.toString()
        )
        expect(sessionRecording.events.map((event) => event.uuid)).toStrictEqual(
            messages.map((message) => message.headers.eventId.toString())
        )
    })

    // TODO: implement producing messages for ClickHouse to read
    it.skip('produces messages to Kafka for the purposes of analytics, e.g. ClickHouse queries', () => {})
})

const getSessionRecording = async (teamId: string, sessionId: string): Promise<{ events: any[] }> => {
    const options = {
        hostname: 'localhost',
        port: 3000,
        path: `/api/team/${teamId}/session_recordings/${sessionId}`,
        method: 'GET',
    }

    return new Promise((resolve, reject) => {
        const req = http.request(options, (res) => {
            let body = ''
            res.on('data', (data) => {
                body = body + data
            })
            res.on('end', () => resolve(JSON.parse(body)))
            res.on('error', (err) => reject(err))
        })

        req.end()
    })
}

const waitForSessionRecording = async (teamId: string, sessionId: string, eventUuid: string) => {
    while (true) {
        const recording = await getSessionRecording(teamId, sessionId)
        if (recording.events.map((event) => event.uuid).includes(eventUuid)) {
            return recording
        }
        await new Promise((resolve) => setTimeout(resolve, 1000))
    }
}

beforeEach(async (context) => {
    const kafka = new Kafka({
        clientId: 'session-recordings',
        brokers: ['localhost:9092'],
    })

    const producer = kafka.producer({ createPartitioner: Partitioners.DefaultPartitioner })
    await producer.connect()

    context.producer = producer
})

afterEach(async ({ producer }) => {
    await producer.disconnect()
})
