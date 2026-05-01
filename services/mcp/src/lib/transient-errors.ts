// Transient errors that signal a normal Cloudflare runtime lifecycle event
// (durable object reset, websocket teardown) rather than a real bug. They
// fire when the DO is replaced after a deploy or hibernation cycle, so they
// produce a lot of error-level log noise that we want demoted to warn.
const TRANSIENT_PATTERNS: readonly RegExp[] = [
    /webSocketClose:/i,
    /webSocketError:/i,
    /\bdestroyed\b/i,
    /Durable Object reset/i,
]

function matches(value: string): boolean {
    return TRANSIENT_PATTERNS.some((pattern) => pattern.test(value))
}

export function isTransientShutdownError(error: unknown): boolean {
    if (!error) {
        return false
    }
    if (error instanceof Error) {
        return matches(error.message) || (typeof error.stack === 'string' && matches(error.stack))
    }
    return matches(String(error))
}

// Demote console.error calls whose serialized arguments match a transient
// pattern to console.warn. Keeps unrelated error logs intact. Idempotent.
let consoleFilterInstalled = false

export function installTransientConsoleFilter(): void {
    if (consoleFilterInstalled) {
        return
    }
    consoleFilterInstalled = true

    const originalError = console.error.bind(console)
    const originalWarn = console.warn.bind(console)

    console.error = (...args: unknown[]): void => {
        const serialized = args
            .map((arg) => {
                if (typeof arg === 'string') {
                    return arg
                }
                if (arg instanceof Error) {
                    return `${arg.name}: ${arg.message}`
                }
                return ''
            })
            .join(' ')

        if (matches(serialized)) {
            originalWarn('[MCP transient]', ...args)
            return
        }
        originalError(...args)
    }
}
