/** @type {import('next').NextConfig} */
const nextConfig = {
    reactStrictMode: true,
    // The console embeds @posthog/agent-chat from the workspace; transpile it
    // alongside the console's own source so Next.js compiles the .tsx instead
    // of looking for a prebuilt dist (the package ships source-only for now).
    transpilePackages: ['@posthog/agent-chat', '@posthog/quill', '@posthog/quill-tokens'],
}

export default nextConfig
