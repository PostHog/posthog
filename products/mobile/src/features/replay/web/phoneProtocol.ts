// Mirrors common/replay-headless/src/phone-protocol.ts. The app cannot import it: builds upload only products/mobile.

export interface PhoneSource {
    startTs: number
    endTs: number
}

export type PhoneHostCommand =
    | { type: 'init'; sessionId: string; sources: PhoneSource[]; speed: number; skipInactivity: boolean }
    | { type: 'prepare'; targetTs: number; endTs: number | null; play: boolean }
    /** Moves only the end of the window, so playback goes on from where it is. */
    | { type: 'window'; endTs: number | null }
    | { type: 'seek'; ts: number }
    | { type: 'play' }
    | { type: 'pause' }
    | { type: 'speed'; speed: number }
    | { type: 'skipInactivity'; on: boolean }
    | { type: 'blocks'; requestId: number; text: string; done: boolean }
    | { type: 'blocksFailed'; requestId: number; message: string }

export type PhonePlayerMessage =
    | { type: 'loaded' }
    | { type: 'need'; requestId: number; from: number; to: number }
    | { type: 'status'; status: 'loading' | 'readyToPlay' | 'error'; message?: string }
    | { type: 'time'; ts: number; playing: boolean }
    | { type: 'firstFrame'; ts: number }
    | { type: 'ended' }
    | { type: 'mark'; name: string; at: number; detail?: Record<string, number | string> }
    | { type: 'log'; level: 'error' | 'warn'; message: string }

const STATUSES = new Set(['loading', 'readyToPlay', 'error'])

function isInt(value: unknown, min: number, max: number): value is number {
    return typeof value === 'number' && Number.isSafeInteger(value) && value >= min && value <= max
}

function isNumber(value: unknown): value is number {
    return typeof value === 'number' && Number.isFinite(value)
}

function shortText(value: unknown): value is string {
    return typeof value === 'string' && value.length <= 2000
}

/** The page renders customer content, so every message from it is untrusted and checked field by field. */
export function parsePlayerMessage(raw: string, blockCount: number): PhonePlayerMessage | null {
    let value: unknown
    try {
        value = JSON.parse(raw)
    } catch {
        return null
    }
    if (typeof value !== 'object' || value === null) {
        return null
    }
    const message = value as Record<string, unknown>
    switch (message.type) {
        case 'loaded':
        case 'ended':
            return { type: message.type }
        case 'need':
            return isInt(message.requestId, 1, 1_000_000) &&
                isInt(message.from, 0, blockCount - 1) &&
                isInt(message.to, 0, blockCount - 1) &&
                message.to >= message.from &&
                message.to - message.from <= 100
                ? { type: 'need', requestId: message.requestId, from: message.from, to: message.to }
                : null
        case 'status':
            return typeof message.status === 'string' && STATUSES.has(message.status)
                ? {
                      type: 'status',
                      status: message.status as 'loading' | 'readyToPlay' | 'error',
                      message: shortText(message.message) ? message.message : undefined,
                  }
                : null
        case 'time':
            return isNumber(message.ts) ? { type: 'time', ts: message.ts, playing: message.playing === true } : null
        case 'firstFrame':
            return isNumber(message.ts) ? { type: 'firstFrame', ts: message.ts } : null
        case 'mark': {
            if (!shortText(message.name) || !isNumber(message.at)) {
                return null
            }
            const detail: Record<string, number | string> = {}
            if (typeof message.detail === 'object' && message.detail !== null) {
                for (const [key, item] of Object.entries(message.detail).slice(0, 12)) {
                    if (isNumber(item) || shortText(item)) {
                        detail[key] = item
                    }
                }
            }
            return { type: 'mark', name: message.name, at: message.at, detail }
        }
        case 'log':
            return shortText(message.message)
                ? { type: 'log', level: message.level === 'warn' ? 'warn' : 'error', message: message.message }
                : null
        default:
            return null
    }
}

export function commandScript(command: PhoneHostCommand): string {
    return `window.__phonePlayer&&window.__phonePlayer.command(${JSON.stringify(command)});true;`
}
