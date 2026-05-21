import { createSessionLogger, FakeLogProducer, InMemorySessionBus, SessionEvent } from '@posthog/agent-core'

import { BusBridgingRegistry } from './ass-server-bridge'

describe('BusBridgingRegistry — streaming deltas', () => {
    const teamId = 7
    const applicationId = '00000000-0000-0000-0000-0000000000aa'
    const sessionId = '00000000-0000-0000-0000-0000000000bb'

    it('forwards message_delta emits onto the bus but never persists them', async () => {
        const bus = new InMemorySessionBus()
        const producer = new FakeLogProducer()
        const sessionLogger = createSessionLogger({ teamId, applicationId, sessionId, producer })

        const received: SessionEvent[] = []
        await bus.subscribeEvents(sessionId, (e) => received.push(e))

        const bridge = new BusBridgingRegistry(bus, sessionId, sessionLogger)
        bridge.emit('ass-session', 'message_delta', { text: 'Hel' })
        bridge.emit('ass-session', 'message_delta', { text: 'lo' })
        bridge.emit('ass-session', 'assistant_message', { content: 'Hello' })

        // Live bus subscribers see every delta plus the final message.
        expect(received.map((e) => e.type)).toEqual(['message_delta', 'message_delta', 'message'])
        expect(received.filter((e) => e.type === 'message_delta')).toEqual([
            { type: 'message_delta', at: expect.any(String), text: 'Hel' },
            { type: 'message_delta', at: expect.any(String), text: 'lo' },
        ])

        // ClickHouse log carries only the durable message — zero delta rows.
        expect(producer.entries.map((e) => e.message)).toEqual(['[chat] assistant: Hello'])
    })

    it('drops a message_delta emit that carries no text payload', async () => {
        const bus = new InMemorySessionBus()
        const producer = new FakeLogProducer()
        const sessionLogger = createSessionLogger({ teamId, applicationId, sessionId, producer })

        const received: SessionEvent[] = []
        await bus.subscribeEvents(sessionId, (e) => received.push(e))

        const bridge = new BusBridgingRegistry(bus, sessionId, sessionLogger)
        bridge.emit('ass-session', 'message_delta', { notText: true })

        expect(received).toEqual([])
        expect(producer.entries).toEqual([])
    })
})
