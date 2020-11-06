import { ConsoleExtension } from 'posthog-plugins'

export function createConsole(): ConsoleExtension {
    return {
        log: (...args: unknown[]): void => console.log(...args),
        error: (...args: unknown[]): void => console.error(...args),
        debug: (...args: unknown[]): void => console.debug(...args),
    }
}
