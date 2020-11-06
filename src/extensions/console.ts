interface ConsoleExtension {
    log: (...args: unknown[]) => void
    error: (...args: unknown[]) => void
    debug: (...args: unknown[]) => void
}

export function createConsole(): ConsoleExtension {
    return {
        log: (...args: unknown[]): void => console.log(...args),
        error: (...args: unknown[]): void => console.error(...args),
        debug: (...args: unknown[]): void => console.debug(...args),
    }
}
