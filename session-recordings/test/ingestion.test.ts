import { beforeEach, afterEach, beforeAll, expect, it, describe } from 'vitest'
import { Kafka, Partitioners, Producer } from 'kafkajs'
import http from 'http'
import { v4 as uuidv4 } from 'uuid'
import { gzipSync } from 'zlib'

declare module 'vitest' {
    export interface TestContext {
        producer: Producer
    }
}

describe.concurrent('ingester', () => {
    it('handles one event', async ({ producer }) => {
        const teamId = uuidv4()
        const sessionId = uuidv4()
        const windowId = uuidv4()
        const eventUuid = uuidv4()

        await producer.send({
            topic: 'events_plugin_ingestion',
            messages: [
                {
                    value: JSON.stringify({
                        event: '$snapshot',
                        team_id: teamId,
                        uuid: eventUuid,
                        timestamp: 1234,
                        data: JSON.stringify({
                            properties: {
                                $session_id: sessionId,
                                $window_id: windowId,
                                $snapshot_data: {
                                    data: gzipSync(JSON.stringify([{ uuid: eventUuid, timestamp: 123 }])).toString(
                                        'base64'
                                    ),
                                },
                            },
                        }),
                    }),
                },
            ],
        })

        const sessionRecording = await waitForSessionRecording(teamId, sessionId, eventUuid)

        expect(sessionRecording.events.length).toBe(1)
    })

    it('handles event larger than the max chunk limit', async ({ producer }) => {
        const teamId = uuidv4()
        const sessionId = uuidv4()
        const windowId = uuidv4()
        const eventUuid = uuidv4()

        await producer.send({
            topic: 'events_plugin_ingestion',
            messages: [
                {
                    value: JSON.stringify({
                        event: '$snapshot',
                        team_id: teamId,
                        uuid: eventUuid,
                        timestamp: 1234,
                        data: JSON.stringify({
                            properties: {
                                $session_id: sessionId,
                                $window_id: windowId,
                                $snapshot_data: {
                                    data: gzipSync(
                                        JSON.stringify([
                                            {
                                                uuid: eventUuid,
                                                timestamp: 123,
                                                data: Array.from(new Array(10000).keys()),
                                            },
                                        ])
                                    ).toString('base64'),
                                },
                            },
                        }),
                    }),
                },
            ],
        })

        const sessionRecording = await waitForSessionRecording(teamId, sessionId, eventUuid)

        expect(sessionRecording.events.length).toBe(1)
    })

    it('handles lots of events', async ({ producer }) => {
        const teamId = uuidv4()
        const sessionId = uuidv4()
        const windowId = uuidv4()

        const events = Array.from(new Array(30).keys()).map((_) => {
            const eventUuid = uuidv4()
            return {
                event: '$snapshot',
                team_id: teamId,
                uuid: eventUuid,
                timestamp: 1234,
                data: JSON.stringify({
                    properties: {
                        $session_id: sessionId,
                        $window_id: windowId,
                        $snapshot_data: {
                            data: gzipSync(JSON.stringify([{ uuid: eventUuid, timestamp: 123 }])).toString('base64'),
                        },
                    },
                }),
            }
        })

        await producer.send({
            topic: 'events_plugin_ingestion',
            messages: events.map((event) => ({
                value: JSON.stringify(event),
            })),
        })

        const sessionRecording = await waitForSessionRecording(teamId, sessionId, events.slice(-1)[0].uuid)
        expect(sessionRecording.events.map((event) => event.uuid)).toStrictEqual(events.map((event) => event.uuid))
    })

    it('ignores non $snapshot events', async ({ producer }) => {
        const teamId = uuidv4()
        const sessionId = uuidv4()
        const windowId = uuidv4()
        const eventUuid = uuidv4()

        await producer.send({
            topic: 'events_plugin_ingestion',
            messages: [
                {
                    value: JSON.stringify({
                        event: '$notasnapshot',
                        team_id: teamId,
                        uuid: eventUuid,
                        timestamp: 1234,
                        data: JSON.stringify({
                            properties: {
                                $session_id: sessionId,
                                $window_id: windowId,
                                $snapshot_data: {
                                    data: gzipSync(JSON.stringify([{ uuid: eventUuid, timestamp: 123 }])).toString(
                                        'base64'
                                    ),
                                },
                            },
                        }),
                    }),
                },
            ],
        })

        const snapshotEventUuid = uuidv4()

        await producer.send({
            topic: 'events_plugin_ingestion',
            messages: [
                {
                    value: JSON.stringify({
                        event: '$snapshot',
                        team_id: teamId,
                        uuid: snapshotEventUuid,
                        timestamp: 1234,
                        data: JSON.stringify({
                            properties: {
                                $session_id: sessionId,
                                $window_id: windowId,
                                $snapshot_data: {
                                    data: gzipSync(
                                        JSON.stringify([{ uuid: snapshotEventUuid, timestamp: 123 }])
                                    ).toString('base64'),
                                },
                            },
                        }),
                    }),
                },
            ],
        })

        const sessionRecording = await waitForSessionRecording(teamId, sessionId, snapshotEventUuid)

        expect(sessionRecording.events.length).toBe(1)
    })
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
