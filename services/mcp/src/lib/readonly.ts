export const getReadOnlyFromRequest = (request: Request, url: URL): boolean | undefined => {
    const readOnlyRaw =
        request.headers.get('x-posthog-readonly') ||
        request.headers.get('x-posthog-read-only') ||
        url.searchParams.get('readonly')
    return readOnlyRaw === 'true' || readOnlyRaw === '1' || undefined
}
