// Shared shape for the per-runtime integration harnesses. Each harness owns
// the lifecycle of a real listener (Hono via `@hono/node-server`, CF via
// `wrangler unstable_dev`) and exposes the URL the MCP SDK client connects to.

export type IntegrationHarness = {
    baseUrl: URL
    /** Stop the listener and release any resources. Idempotent. */
    stop: () => Promise<void>
}

export type IntegrationEnv = {
    apiToken: string
    /** Optional second personal API key. When set, the suite runs the
     * concurrent-sessions isolation test that verifies one client's state
     * doesn't bleed into another's. */
    apiToken2?: string | undefined
    orgId: string
    projectId: string
    apiBaseUrl: string
}

export function loadIntegrationEnv(): IntegrationEnv {
    const apiToken = process.env.TEST_POSTHOG_PERSONAL_API_KEY
    const orgId = process.env.TEST_ORG_ID
    const projectId = process.env.TEST_PROJECT_ID

    if (!apiToken || !orgId || !projectId) {
        throw new Error(
            'Integration tests require TEST_POSTHOG_PERSONAL_API_KEY, TEST_ORG_ID, and TEST_PROJECT_ID to be set. ' +
                'See tests/shared/test-utils.ts for how the existing tool integration tests source these.'
        )
    }

    return {
        apiToken,
        apiToken2: process.env.TEST_POSTHOG_PERSONAL_API_KEY_2 || undefined,
        orgId,
        projectId,
        apiBaseUrl: process.env.TEST_POSTHOG_API_BASE_URL || 'http://localhost:8010',
    }
}
