import { ConsoleExtension } from '@posthog/plugin-scaffold'

export function createConsole(): ConsoleExtension {
    return {
        log: (...args: unknown[]): void => console.log(...args),
        error: (...args: unknown[]): void => console.error(...args),
        info: (...args: unknown[]): void => console.info(...args),
        warn: (...args: unknown[]): void => console.warn(...args),
        debug: (...args: unknown[]): void => console.debug(...args),
    }
}
