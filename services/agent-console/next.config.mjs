/**
 * Same-origin API proxies — keep CORS out of the picture.
 *
 *   `/api/agents/v1/*`  → agent-ingress (runtime + streaming surfaces:
 *                          session lifecycle, /listen, mutation events).
 *                          Declared in `beforeFiles` so it wins against
 *                          the wildcard `/api/*` rewrite below.
 *   `/api/*`            → PostHog Django REST (persistent state).
 *
 * Both base URLs come from env so each deploy points at its region.
 * Fallbacks match the v0 local-dev assumption (PostHog at :8000, no
 * ingress in dev — Storybook handles that via MSW).
 */
const POSTHOG_DJANGO_BASE = process.env.NEXT_PUBLIC_POSTHOG_DJANGO_BASE ?? 'http://localhost:8000'
const POSTHOG_AGENTS_BASE = process.env.NEXT_PUBLIC_POSTHOG_AGENTS_BASE ?? 'http://localhost:3010'

/** @type {import('next').NextConfig} */
const nextConfig = {
    reactStrictMode: true,
    // The console embeds @posthog/agent-chat from the workspace; transpile it
    // alongside the console's own source so Next.js compiles the .tsx instead
    // of looking for a prebuilt dist (the package ships source-only for now).
    transpilePackages: ['@posthog/agent-chat', '@posthog/quill', '@posthog/quill-tokens'],
    async rewrites() {
        return {
            beforeFiles: [{ source: '/api/agents/v1/:path*', destination: `${POSTHOG_AGENTS_BASE}/:path*` }],
            afterFiles: [{ source: '/api/:path*', destination: `${POSTHOG_DJANGO_BASE}/api/:path*` }],
            fallback: [],
        }
    },
}

export default nextConfig
