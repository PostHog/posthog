/** @type {import('next').NextConfig} */
const nextConfig = {
    // Proxy posthog-js traffic through the Next server so the remote browser
    // (e.g. a Browserbase agent running through an ngrok tunnel) can reach the
    // local PostHog instance over the same public URL it loaded the site from.
    // Without this, posthog-js inside a remote browser tries to POST to
    // http://localhost:8010 — that's the *remote* container's loopback, where
    // nothing is running, so events drop silently.
    async rewrites() {
        const target = process.env.POSTHOG_REWRITE_TARGET || 'http://localhost:8010'
        return [
            {
                source: '/posthog-proxy/:path*',
                destination: `${target}/:path*`,
            },
            {
                source: '/posthog-proxy',
                destination: target,
            },
        ]
    },
}

module.exports = nextConfig
