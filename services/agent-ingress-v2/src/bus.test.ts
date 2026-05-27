import { MemorySessionEventBus, SessionEvent } from './bus'

describe('MemorySessionEventBus', () => {
    it('delivers events to subscribers of the same session', async () => {
        const bus = new MemorySessionEventBus()
        const received: SessionEvent[] = []
        const unsub = bus.subscribe('s1', (e) => received.push(e))
        await bus.publish({ session_id: 's1', kind: 'assistant_text', data: { text: 'hi' }, ts: 't' })
        expect(received).toHaveLength(1)
        unsub()
        await bus.publish({ session_id: 's1', kind: 'completed', data: {}, ts: 't' })
        expect(received).toHaveLength(1)
    })

    it('isolates by session id', async () => {
        const bus = new MemorySessionEventBus()
        const a: SessionEvent[] = []
        const b: SessionEvent[] = []
        bus.subscribe('a', (e) => a.push(e))
        bus.subscribe('b', (e) => b.push(e))
        await bus.publish({ session_id: 'a', kind: 'assistant_text', data: { text: 'hi a' }, ts: 't' })
        expect(a).toHaveLength(1)
        expect(b).toHaveLength(0)
    })

    it('supports multiple subscribers per session', async () => {
        const bus = new MemorySessionEventBus()
        let count = 0
        bus.subscribe('s', () => count++)
        bus.subscribe('s', () => count++)
        await bus.publish({ session_id: 's', kind: 'completed', data: {}, ts: 't' })
        expect(count).toBe(2)
    })
})
