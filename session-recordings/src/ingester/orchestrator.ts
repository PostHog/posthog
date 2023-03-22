import { IncomingRecordingMessage } from '../types'
import { SessionManager } from './session-manager'

// TODO: This should manage state of sessions, dropping them if flushes are finished
export class Orchestrator {
    private sessions: Map<string, SessionManager> = new Map()

    public consume(event: IncomingRecordingMessage): void {
        const key = `${event.team_id}-${event.session_id}`

        if (!this.sessions.has(key)) {
            this.sessions.set(
                key,
                new SessionManager(event.team_id, event.session_id, () => {
                    // If the SessionManager is done (flushed and with no more queued events) then we remove it to free up memory
                    this.sessions.delete(key)
                })
            )
        }

        this.sessions.get(key).add(event)
    }
}
