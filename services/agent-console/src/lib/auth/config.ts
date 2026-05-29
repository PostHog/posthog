/**
 * Auth config — env-driven URLs + secret.
 *
 * Centralized here so the rest of the auth code doesn't reach into
 * `process.env` directly. Throws loudly on missing required values so
 * deployment misconfigurations surface immediately.
 */

export function posthogBaseUrl(): string {
    const v = process.env.POSTHOG_BASE_URL
    if (!v) {
        throw new Error('POSTHOG_BASE_URL is not set')
    }
    return v.replace(/\/$/, '')
}

export function posthogAgentsBaseUrl(): string {
    const v = process.env.POSTHOG_AGENTS_BASE
    if (!v) {
        throw new Error('POSTHOG_AGENTS_BASE is not set')
    }
    return v.replace(/\/$/, '')
}

export function consoleBaseUrl(): string {
    return (process.env.CONSOLE_BASE_URL ?? 'http://localhost:3040').replace(/\/$/, '')
}

export function cookieSecret(): string {
    const v = process.env.OAUTH_COOKIE_SECRET
    if (!v) {
        throw new Error('OAUTH_COOKIE_SECRET is not set (need at least 32 characters)')
    }
    if (v.length < 32) {
        throw new Error('OAUTH_COOKIE_SECRET must be at least 32 characters')
    }
    return v
}
