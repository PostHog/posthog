import type { SseEvent } from '@/api/sse'
import type { TaskRunApi } from '@/api/tasks'

import type { StoredAnswer } from './handoffStore'
import { applyRunSnapshot, type RunStreamCursor, reduceFrame, type StreamEventResult } from './runStream'
import type { RunStreamState } from './types'

export const HYDRATION_QUIET_MS = 250

export class RunHydration {
    cursor: RunStreamCursor
    state: RunStreamState
    answerAtStart: StoredAnswer | undefined
    settled = false

    constructor(cursor: RunStreamCursor, state: RunStreamState, answer?: StoredAnswer) {
        this.cursor = cursor.fork()
        this.state = { ...state, liveActivitySeen: false }
        this.answerAtStart = answer
    }

    resume(state: RunStreamState, answer?: StoredAnswer): void {
        if (this.settled) {
            this.cursor = this.cursor.fork()
            this.state = { ...state, liveActivitySeen: false }
            this.answerAtStart = answer
            this.settled = false
        }
    }

    applySnapshot(run: TaskRunApi): void {
        this.state = applyRunSnapshot(this.state, run)
    }

    accept(event: SseEvent): StreamEventResult {
        const outcome = this.cursor.accept(event)
        if (!this.settled && outcome.frame) {
            // Redis ids can also be backlog, so historical permission requests must never auto-allow.
            this.state = reduceFrame(this.state, outcome.frame.data, {
                ...outcome.frame.context,
                source: 'replay',
            }).state
        }
        return outcome
    }
}
