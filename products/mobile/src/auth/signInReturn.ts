type RouteParams = Record<string, string | string[] | undefined>

/**
 * The screen to reopen after sign-in, such as the report a link opened while signed out. Null for the start page and
 * the tabs, so a plain sign-in still lands on the start page the user chose.
 */
export function signInReturnHref(pathname: string, segments: readonly string[], params: RouteParams): string | null {
    const first = segments[0]
    if (pathname === '/' || first === undefined || first === 'sign-in' || first === '(tabs)') {
        return null
    }
    // Global search params also carry the dynamic path segments, which are already in the pathname.
    const pathParams = new Set(segments.map((segment) => /^\[(?:\.\.\.)?(\w+)\]$/.exec(segment)?.[1]))
    const query = new URLSearchParams()
    for (const [key, value] of Object.entries(params)) {
        if (pathParams.has(key) || value === undefined) {
            continue
        }
        for (const item of Array.isArray(value) ? value : [value]) {
            query.append(key, item)
        }
    }
    const search = query.toString()
    return search ? `${pathname}?${search}` : pathname
}

/** The `next` param of the sign-in route when it is an in-app path. Anything else could leave the app or loop. */
export function signInReturnParam(value: string | string[] | undefined): string | null {
    const next = Array.isArray(value) ? value[0] : value
    if (next === undefined || !/^\/[^/\\]/.test(next) || /^\/sign-in(?:[/?#]|$)/.test(next)) {
        return null
    }
    return next
}
