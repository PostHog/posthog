import posthog from 'posthog-js'

export function initPostHog(): void {
    if (typeof window !== 'undefined') {
        const demoApiToken = process.env.NEXT_PUBLIC_POSTHOG_KEY
        if (!demoApiToken) {
            console.warn(
                'NEXT_PUBLIC_POSTHOG_KEY is not set, skipping PostHog initialization.\n' +
                    'Run "npm run fetch-key" to automatically fetch the key from the database.'
            )
            return
        }
        // Default to a same-origin rewrite path (see next.config.js) so the site works
        // identically when visited locally and when proxied through ngrok to a remote
        // browser (e.g. a Browserbase agent). Override with NEXT_PUBLIC_POSTHOG_HOST
        // if you have an absolute reachable URL.
        const localApiHost = process.env.NEXT_PUBLIC_POSTHOG_HOST || '/posthog-proxy'
        posthog.init(demoApiToken, {
            api_host: localApiHost,
            disable_compression: true,
            capture_pageview: false,
            autocapture: true,
            persistence: 'memory', // Use memory persistence for replay mode to avoid conflicts
            opt_out_useragent_filter: true, // We do want capture to work in a bot environment (Playwright)
        })
        console.info(`PostHog initialized for Hedgebox with host: ${localApiHost}, api token: ${demoApiToken}`)
    }
    ;(window as any).posthog = posthog
}

export { posthog }
