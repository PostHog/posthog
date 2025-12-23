// Runtime detection for environment variables
// Works in both Cloudflare Workers and Node.js
function getEnvVar(name: string): string | undefined {
    // Node.js
    if (typeof process !== 'undefined' && process.env) {
        return process.env[name]
    }
    // Cloudflare Workers - env is passed via bindings, not a global
    return undefined
}

export const CUSTOM_BASE_URL = getEnvVar('POSTHOG_BASE_URL')

export const MCP_DOCS_URL = 'https://posthog.com/docs/model-context-protocol'
