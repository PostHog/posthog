// The MCP Redis client runs with `enableOfflineQueue: false`, so every command
// issued during a reconnect window (deploy, failover, idle drop) rejects at once
// instead of waiting for the socket. These are the rejections that carry no
// information about the data — only about the transport — so a cache read can
// treat them as a miss and a cache warm can drop the value.
const TRANSIENT_MESSAGE_FRAGMENTS = [
    "Stream isn't writeable",
    'Connection is closed',
    'Connection is already closed',
    'Command timed out',
    'max retries per request',
]

const TRANSIENT_SOCKET_CODES = new Set([
    'ECONNREFUSED',
    'ECONNRESET',
    'EHOSTUNREACH',
    'ENETUNREACH',
    'ENOTFOUND',
    'EPIPE',
    'ETIMEDOUT',
    'EAI_AGAIN',
])

export function isTransientRedisError(error: unknown): boolean {
    if (!(error instanceof Error)) {
        return false
    }
    const code = (error as NodeJS.ErrnoException).code
    if (typeof code === 'string' && TRANSIENT_SOCKET_CODES.has(code)) {
        return true
    }
    return TRANSIENT_MESSAGE_FRAGMENTS.some((fragment) => error.message.includes(fragment))
}
