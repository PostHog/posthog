import { sleep } from '@/lib/sleep'

/** Time source for retry loops, so tests can run them without waiting. */
export interface Clock {
    now: () => number
    sleep: (ms: number, signal?: AbortSignal) => Promise<void>
}

export const realClock: Clock = { now: () => Date.now(), sleep }
