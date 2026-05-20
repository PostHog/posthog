/**
 * Test-only export of the level-method patch so the logger tests can verify
 * arg-order handling without depending on the global `logger` singleton's
 * stream configuration.
 */
import { ChildLoggerOptions, Logger as PinoLogger } from 'pino'

const LEVEL_METHODS = ['fatal', 'error', 'warn', 'info', 'debug', 'trace'] as const

export function patchForTest<T extends PinoLogger>(target: T): T {
    for (const method of LEVEL_METHODS) {
        const original = target[method].bind(target) as (...args: unknown[]) => void
        const patched = (...args: unknown[]): void => {
            if (
                args.length >= 2 &&
                typeof args[0] === 'string' &&
                typeof args[1] === 'object' &&
                args[1] !== null &&
                !Array.isArray(args[1])
            ) {
                original(args[1], args[0], ...args.slice(2))
                return
            }
            original(...args)
        }
        ;(target as unknown as Record<string, unknown>)[method] = patched
    }
    const originalChild = target.child.bind(target)
    ;(target as unknown as Record<string, unknown>).child = (
        bindings: Record<string, unknown>,
        opts?: ChildLoggerOptions
    ): PinoLogger => patchForTest(originalChild(bindings, opts))
    return target
}
