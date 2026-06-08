import { strToU8, zipSync } from 'fflate'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

// The Hono/CF harness warms up by downloading the context-mill resource bundle
// from this GitHub release. Letting an integration suite depend on a live CDN
// makes the harness `beforeAll` flaky (slow downloads blow the hook budget), so
// we stub the download with an in-process MSW server serving a minimal bundle.
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

// `onUnhandledRequest: 'bypass'` (set by callers on `.listen()`) lets the real
// requests to the local PostHog stack and the harness's own listener flow
// through untouched — only the context-mill download is stubbed.
export const contextMillFixtureServer = setupServer(
    http.get(CONTEXT_MILL_URL, () => new HttpResponse(zip, { headers: { 'Content-Type': 'application/zip' } }))
)
