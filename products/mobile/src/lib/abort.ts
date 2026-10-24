/** A plain `Error` named `AbortError`. Callers check the name, so this also works in runtimes without `DOMException`. */
export function abortError(): Error {
    const error = new Error('Aborted')
    error.name = 'AbortError'
    return error
}
