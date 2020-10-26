export function createConsole () {
    return {
        log: (...args) => console.log(...args),
        error: (...args) => console.error(...args),
        debug: (...args) => console.debug(...args)
    }
}