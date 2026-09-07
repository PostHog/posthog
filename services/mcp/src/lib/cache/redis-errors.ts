// `enableOfflineQueue: false` makes every command reject at once during a reconnect
// window. These rejections describe the transport, not the data behind a key.
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

// A failover can demote the old primary in place, so a write replies READONLY over a
// socket that is otherwise healthy. That describes the topology, not the data behind a key.
const READ_ONLY_REPLICA_REPLY = 'READONLY'

export function isTransientRedisError(error: unknown): error is Error {
    if (!(error instanceof Error)) {
        return false
    }
    const code = (error as NodeJS.ErrnoException).code
    if (typeof code === 'string' && TRANSIENT_SOCKET_CODES.has(code)) {
        return true
    }
    if (error.message.startsWith(READ_ONLY_REPLICA_REPLY)) {
        return true
    }
    return TRANSIENT_MESSAGE_FRAGMENTS.some((fragment) => error.message.includes(fragment))
}
