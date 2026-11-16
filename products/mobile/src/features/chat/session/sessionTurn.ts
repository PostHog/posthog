import { isTerminalRunStatus } from '@/features/handoff/runStream'
import type { RunStreamState } from '@/features/handoff/types'
import { track } from '@/lib/analytics'

export type SessionTurnOutcome = 'completed' | 'failed' | 'cancelled' | 'stopped' | 'abandoned'

interface PendingTurn {
    runId: string
    sentAt: number
    /** False until the run shows this turn as open, so the end of the turn before it does not count. */
    open: boolean
    hadDecision: boolean
    stopped: boolean
    errorMessage: string | undefined
}

/**
 * Sends one `mobile_session_finished` per sent message: when its turn ends, its run ends, or the chat drops it
 * (`abandoned`). `mobile_session_stopped` stays the Stop tap; a stopped turn finishes here as `stopped`.
 */
export class SessionTurnTracker {
    private turn: PendingTurn | null = null

    constructor(private readonly now: () => number = Date.now) {}

    begin(state: RunStreamState | null): void {
        if (!state) {
            return
        }
        this.turn = {
            runId: state.runId,
            sentAt: this.now(),
            open: !state.turnEnded && !isTerminalRunStatus(state.status),
            hadDecision: false,
            stopped: false,
            errorMessage: state.errorMessage,
        }
    }

    /**
     * A steered message joins the turn it steers, so one `mobile_session_finished` covers both. `begin` would restart
     * the open turn's clock and clear its `had_decision`.
     */
    join(state: RunStreamState | null): void {
        if (this.turn && this.turn.runId === state?.runId) {
            return
        }
        this.begin(state)
    }

    observe(state: RunStreamState | null): void {
        const turn = this.turn
        if (!turn || !state || state.runId !== turn.runId) {
            return
        }
        if (state.pending) {
            turn.hadDecision = true
        }
        if (isTerminalRunStatus(state.status)) {
            if (state.status === 'cancelled') {
                this.finish(turn.stopped ? 'stopped' : 'cancelled')
            } else {
                this.finish(state.status === 'failed' ? 'failed' : 'completed')
            }
            return
        }
        if (!state.turnEnded) {
            turn.open = true
            return
        }
        if (!turn.open) {
            return
        }
        if (turn.stopped) {
            this.finish('stopped')
        } else {
            this.finish(
                state.errorMessage !== undefined && state.errorMessage !== turn.errorMessage ? 'failed' : 'completed'
            )
        }
    }

    /** `stopped: false` undoes a Stop whose cancel command failed, so the turn can still complete. */
    markStopped(stopped: boolean): void {
        if (this.turn) {
            this.turn.stopped = stopped
        }
    }

    finish(status: SessionTurnOutcome): void {
        const turn = this.turn
        if (!turn) {
            return
        }
        this.turn = null
        track('mobile_session_finished', {
            status,
            duration_s: Math.round((this.now() - turn.sentAt) / 1000),
            had_decision: turn.hadDecision,
        })
    }
}
