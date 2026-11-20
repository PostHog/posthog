const RETURN_LIFETIME_MS = 60 * 60 * 1000

function returnKey(teamId: number): string {
    return `inbox-mobile-return-${teamId}`
}

export function mobileInboxReturnUrl(scheme: unknown): string | null {
    return scheme === 'posthog' || scheme === 'posthog-dev' || scheme === 'posthog-preview' ? `${scheme}://inbox` : null
}

export function rememberMobileInboxReturn(teamId: number, scheme: unknown): void {
    const url = mobileInboxReturnUrl(scheme)
    if (!url) {
        return
    }
    try {
        window.sessionStorage.setItem(
            returnKey(teamId),
            JSON.stringify({ url, expires: Date.now() + RETURN_LIFETIME_MS })
        )
    } catch {
        // Setup must still work when the browser refuses session storage.
    }
}

export function getMobileInboxReturn(teamId: number | null): string | null {
    if (!teamId) {
        return null
    }
    try {
        const saved = JSON.parse(window.sessionStorage.getItem(returnKey(teamId)) ?? 'null')
        if (
            saved &&
            saved.expires > Date.now() &&
            ['posthog://inbox', 'posthog-dev://inbox', 'posthog-preview://inbox'].includes(saved.url)
        ) {
            return saved.url
        }
    } catch {
        return null
    }
    return null
}
