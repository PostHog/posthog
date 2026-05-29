/** @type {import('next').NextConfig} */
const nextConfig = {
    reactStrictMode: true,
    // The console embeds @posthog/agent-chat from the workspace; transpile it
    // alongside the console's own source so Next.js compiles the .tsx instead
    // of looking for a prebuilt dist (the package ships source-only for now).
    transpilePackages: ['@posthog/agent-chat', '@posthog/quill', '@posthog/quill-tokens'],
    // Django REST routes end in `/`; without this Next.js's default 308
    // redirect strips the trailing slash and the catch-all proxy forwards
    // a URL Django doesn't recognize.
    skipTrailingSlashRedirect: true,
    // Emits a minimal self-contained server bundle under `.next/standalone/`
    // for the container image — see services/agent-console/Dockerfile.
    output: 'standalone',
    // The standalone output traces dependencies from this file outward.
    // Pinning the workspace root makes the trace deterministic across
    // local + docker builds (otherwise next picks a parent dir as root).
    outputFileTracingRoot: new URL('../../', import.meta.url).pathname,
}

export default nextConfig
