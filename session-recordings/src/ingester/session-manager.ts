import { ParsedKafkaMessage } from '../types'

// The buffer is a list of messages grouped
type SessionBuffer = {
    id: string
    count: number
    size: number
    createdAt: Date
    messages: ParsedKafkaMessage[]
}

export class SessionManager {
    chunks: Map<string, ParsedKafkaMessage[]> = new Map()
    buffer: SessionBuffer
    flushBuffer?: SessionBuffer

    constructor(public readonly teamId: string, public readonly sessionId: string) {}

    public add(message: any) {
        // Check if it is chunked
        // If not or if full chunk is received, add to ordered queue
    }
}

export class GlobalSessionManager {
    private static sessions: Map<string, SessionManager> = new Map()

    public static consume(event: ParsedKafkaMessage): void {
        const { team_id, session_id } = event.event

        const key = `${team_id}-${session_id}`

        if (!this.sessions.has(key)) {
            this.sessions.set(key, new SessionManager(team_id, session_id))
        }

        this.sessions.get(key).add(event)
    }
}
