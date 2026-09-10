import { beforeEach, describe, expect, it, vi } from 'vitest'

const { analyticsMockState } = vi.hoisted(() => {
    const state = {
        constructThrows: false,
        registerThrows: false,
        instances: [] as Array<{ captures: string[]; register(options: Record<string, unknown>): void }>,
    }
    return { analyticsMockState: state }
})

vi.mock('posthog-js-lite', () => ({
    PostHog: class {
        captures: string[] = []

        constructor() {
            if (analyticsMockState.constructThrows) {
                throw new Error('SecurityError reading localStorage')
            }
            analyticsMockState.instances.push(this)
        }

        register(): void {
            if (analyticsMockState.registerThrows) {
                throw new Error('register failed')
            }
        }

        identify(): void {}

        capture(event: string): void {
            this.captures.push(event)
        }
    },
}))

beforeEach(() => {
    analyticsMockState.constructThrows = false
    analyticsMockState.registerThrows = false
    analyticsMockState.instances = []
    vi.resetModules()
    vi.unstubAllGlobals()
})

async function loadAnalytics(): Promise<typeof import('@/ui-apps/analytics/posthog')> {
    // The analytics token is a build-time constant; the unit tests run without
    // it, so stub it to reach the initialization path at all.
    vi.stubGlobal('__POSTHOG_UI_APPS_TOKEN__', 'phc_test_token')
    return await import('@/ui-apps/analytics/posthog')
}

describe('ui-apps posthog analytics', () => {
    it('captures events after a successful initialization', async () => {
        const { initPostHog, captureAppConnected } = await loadAnalytics()

        initPostHog('app', '1.0.0')
        captureAppConnected()

        expect(analyticsMockState.instances).toHaveLength(1)
        expect(analyticsMockState.instances[0]?.captures).toContain('mcp_ui_app_connected')
    })

    it('keeps the app rendering when the client constructor throws (regression)', async () => {
        analyticsMockState.constructThrows = true
        const { initPostHog, captureAppConnected } = await loadAnalytics()

        expect(() => initPostHog('app', '1.0.0')).not.toThrow()
        expect(() => captureAppConnected()).not.toThrow()
        expect(analyticsMockState.instances).toHaveLength(0)
    })

    it('keeps the app rendering when register throws (regression)', async () => {
        analyticsMockState.registerThrows = true
        const { initPostHog, captureAppConnected } = await loadAnalytics()

        // The client exists, but the failed register must reset it, so no
        // event reaches the half-initialized client.
        expect(() => initPostHog('app', '1.0.0')).not.toThrow()
        expect(() => captureAppConnected()).not.toThrow()
        expect(analyticsMockState.instances).toHaveLength(1)
        expect(analyticsMockState.instances[0]?.captures).toHaveLength(0)
    })
})
