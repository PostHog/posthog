import { strToU8, zipSync } from 'fflate'

// The Hono/CF harness warms up by downloading the context-mill resource bundle
// from this GitHub release. Letting an integration suite depend on a live CDN
// makes the harness `beforeAll` flaky (slow downloads blow the hook budget), so
// we stub just that one download with a minimal in-memory bundle.
//
// We deliberately patch `globalThis.fetch` directly rather than reach for a
// request-mocking library: the MCP protocol uses a streaming HTTP transport
// between the SDK client and the harness listener, and a lower-level fetch
// interceptor mangles those streaming responses (the suite hangs). A thin
// wrapper that delegates every non-matching request to the real fetch leaves
// the transport untouched.
const CONTEXT_MILL_URL = 'https://github.com/PostHog/context-mill/releases/latest/download/skills-mcp-resources.zip'

// Mirror of the real bundle shape — one `posthog://` resource is enough for
// `defineResourceCatalogTests` to see a readable context-mill entry.
const manifest = {
    version: '1.0.0',
    resources: [
        {
            id: 'test-guide',
            name: 'PostHog Getting Started',
            uri: 'posthog://guide/getting-started',
            resource: {
                mimeType: 'text/plain',
                description: 'A guide to getting started with PostHog',
                text: 'Welcome to PostHog. This is a test resource.',
            },
        },
    ],
}

const zip = zipSync({ 'manifest.json': strToU8(JSON.stringify(manifest)) })

function requestUrl(input: RequestInfo | URL): string {
    if (typeof input === 'string') {
        return input
    }
    if (input instanceof URL) {
        return input.href
    }
    return input.url
}

let realFetch: typeof globalThis.fetch | undefined

export function installContextMillStub(): void {
    if (realFetch) {
        return
    }
    const original = globalThis.fetch
    realFetch = original
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        if (requestUrl(input) === CONTEXT_MILL_URL) {
            // Fresh copy per call so the body can be consumed by repeated reads.
            return new Response(zip.slice(), { headers: { 'Content-Type': 'application/zip' } })
        }
        return original(input, init)
    }) as typeof globalThis.fetch
}

export function uninstallContextMillStub(): void {
    if (realFetch) {
        globalThis.fetch = realFetch
        realFetch = undefined
    }
}
