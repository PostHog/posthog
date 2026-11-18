/**
 * Request validation primitives.
 *
 * A `Validator` is a pure function of the request that returns a `ValidationError`
 * when a rule is broken, or `null` when it passes. Routes declare validators in
 * `index.ts` and the router runs them before the handler, so request-shape rules
 * live in one place instead of being smeared across controllers.
 *
 * Validators are intentionally synchronous and stateless. Rules that need I/O
 * (e.g. checking a value against a stored KV mapping) stay in the handler, which
 * can still reuse `ValidationError` + `errorResponse` for a consistent 400.
 */

export interface ValidationError {
    error: string
    error_description: string
}

export type Validator = (request: Request, url: URL) => ValidationError | null

/** Render a `ValidationError` as an OAuth-style 400 JSON response. */
export function errorResponse(error: ValidationError, extraHeaders: Record<string, string> = {}): Response {
    return new Response(JSON.stringify(error), {
        status: 400,
        headers: { 'Content-Type': 'application/json', ...extraHeaders },
    })
}

/** Run validators in order, returning the first failure (or `null` if all pass). */
export function runValidators(validators: Validator[], request: Request, url: URL): ValidationError | null {
    for (const validate of validators) {
        const error = validate(request, url)
        if (error) {
            return error
        }
    }
    return null
}

/**
 * OAuth request parameters MUST NOT be included more than once (RFC 6749 §3.1). A handler that
 * parses a form body checks that itself, because a `Validator` cannot read the body.
 */
export function findDuplicateParam(params: URLSearchParams, names: readonly string[]): string | null {
    for (const name of names) {
        if (params.getAll(name).length > 1) {
            return name
        }
    }
    return null
}

export function duplicateParamError(param: string): ValidationError {
    return {
        error: 'invalid_request',
        error_description: `Duplicate ${param} parameter is not allowed`,
    }
}

/** Rejects a request that repeats any of the named query params. */
export function noDuplicateParams(...params: string[]): Validator {
    return (_request, url) => {
        const duplicate = findDuplicateParam(url.searchParams, params)
        return duplicate ? duplicateParamError(duplicate) : null
    }
}
