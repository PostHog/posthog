import type { WebSocket } from 'ws'

import type { Answer } from './agent'

export type StageMessage =
    | { type: 'idle' }
    | { type: 'caption'; speaker: string; text: string }
    | { type: 'heard'; question: string }
    | { type: 'thinking' }
    | { type: 'answer'; answer: Answer; audioUrl: string }
    | { type: 'error'; message: string }

/**
 * Fan-out to the webpage Recall renders as the bot's camera.
 *
 * Recall may reload or re-open the page, so the most recent message is replayed to each new connection.
 * Without that the feed would go blank mid-answer on a reconnect.
 */
export class Stage {
    private readonly clients = new Set<WebSocket>()
    private lastMessage: StageMessage = { type: 'idle' }

    attach(socket: WebSocket, onSpoken: () => void): void {
        this.clients.add(socket)
        socket.send(JSON.stringify(this.lastMessage))

        socket.on('message', (raw) => {
            try {
                const parsed = JSON.parse(raw.toString()) as { type?: string }
                if (parsed.type === 'spoken') {
                    onSpoken()
                }
            } catch {
                // A malformed frame from the page is not worth dropping the connection over.
            }
        })
        socket.on('close', () => this.clients.delete(socket))
    }

    send(message: StageMessage): void {
        // Captions are transient, so replaying one to a reconnecting page would strand a stale line on screen.
        if (message.type !== 'caption') {
            this.lastMessage = message
        }
        const payload = JSON.stringify(message)
        for (const client of this.clients) {
            if (client.readyState === client.OPEN) {
                client.send(payload)
            }
        }
    }
}
