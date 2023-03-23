import { beforeEach, expect, it, describe } from 'vitest'
import { Producer } from 'kafkajs'

import { Orchestrator } from './orchestrator'
import { createIncomingRecordingMessage } from '../../test/fixtures'

declare module 'vitest' {
    export interface TestContext {
        producer: Producer
    }
}

describe.concurrent('ingester', () => {
    let orchestrator: Orchestrator
    beforeEach(async () => {
        orchestrator = new Orchestrator()
    })

    it('creates a new session manager if needed', () => {
        const event = createIncomingRecordingMessage()
        orchestrator.consume(event)
        expect(orchestrator.sessions.size).toBe(1)
        expect(orchestrator.sessions.has('1-session_id_1')).toEqual(true)
    })

    it('handles multiple incoming sessions', () => {
        const event = createIncomingRecordingMessage()
        const event2 = createIncomingRecordingMessage({
            session_id: 'session_id_2',
        })
        orchestrator.consume(event)
        orchestrator.consume(event2)
        expect(orchestrator.sessions.size).toBe(2)
        expect(orchestrator.sessions.has('1-session_id_1')).toEqual(true)
        expect(orchestrator.sessions.has('1-session_id_2')).toEqual(true)
    })

    it('destroys a session manager if finished', async () => {
        const event = createIncomingRecordingMessage()
        await orchestrator.consume(event)
        expect(orchestrator.sessions.has('1-session_id_1')).toEqual(true)
        await orchestrator.sessions.get('1-session_id_1')?.flush()
        expect(orchestrator.sessions.has('1-session_id_1')).toEqual(false)
    })

    it.skip('parses incoming kafka messages correctly', () => {})
})
