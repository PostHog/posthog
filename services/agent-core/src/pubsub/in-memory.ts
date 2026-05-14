import { EventEmitter } from 'node:events'

import { SessionBus, SessionEvent, SessionEventListener, SessionInputListener, SessionInputMessage } from './types'

/**
 * In-process implementation for tests and single-node dev. Not suitable for production
 * because /listen subscribers and the runner generally live in different processes.
 */
export class InMemorySessionBus implements SessionBus {
    private readonly emitter = new EventEmitter()

    constructor() {
        // EventEmitter defaults to 10 listeners. We can plausibly have many concurrent
        // /listen subscribers per session on a busy node, so bump it.
        this.emitter.setMaxListeners(0)
    }

    publishEvent(sessionId: string, event: SessionEvent): Promise<void> {
        this.emitter.emit(this.eventChannel(sessionId), event)
        return Promise.resolve()
    }

    subscribeEvents(sessionId: string, listener: SessionEventListener): Promise<() => Promise<void>> {
        const channel = this.eventChannel(sessionId)
        this.emitter.on(channel, listener)
        return Promise.resolve(() => {
            this.emitter.off(channel, listener)
            return Promise.resolve()
        })
    }

    publishInput(sessionId: string, message: SessionInputMessage): Promise<void> {
        this.emitter.emit(this.inputChannel(sessionId), message)
        return Promise.resolve()
    }

    subscribeInput(sessionId: string, listener: SessionInputListener): Promise<() => Promise<void>> {
        const channel = this.inputChannel(sessionId)
        this.emitter.on(channel, listener)
        return Promise.resolve(() => {
            this.emitter.off(channel, listener)
            return Promise.resolve()
        })
    }

    disconnect(): Promise<void> {
        this.emitter.removeAllListeners()
        return Promise.resolve()
    }

    private eventChannel(sessionId: string): string {
        return `agent_session:${sessionId}`
    }

    private inputChannel(sessionId: string): string {
        return `agent_session:${sessionId}:input`
    }
}
