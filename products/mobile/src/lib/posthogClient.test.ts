import PostHog from 'posthog-react-native'

import { useAuthStore } from '@/auth/authStore'

import { actionTracker, setAnalyticsClient, setAnalyticsContextProvider, setAnalyticsScreenContext } from './analytics'
import { initAnalytics } from './posthogClient'

jest.mock('posthog-react-native', () => jest.fn())
jest.mock('@/auth/tokens', () => ({ sessionGeneration: () => 1 }))
jest.mock('@/auth/authStore', () => {
    const state = {
        host: 'https://us.posthog.com',
        status: 'signed_in',
        projectId: 7,
        user: { uuid: 'example-user' },
        projects: [{ id: 7, uuid: 'example-project', organizationId: 'example-org' }],
    }
    return { useAuthStore: { getState: () => state, subscribe: jest.fn() } }
})
jest.mock('@/demo/demoMode', () => ({
    useDemoMode: {
        getState: () => ({ enabled: false }),
        subscribe: jest.fn(),
        persist: { hasHydrated: () => true, onFinishHydration: jest.fn() },
    },
}))

test('lifecycle events redact launch URLs and async events keep the initiating project groups', () => {
    const capture = jest.fn()
    jest.mocked(PostHog).mockImplementation(
        () =>
            ({
                capture,
                resetPersonPropertiesForFlags: jest.fn(),
                setPersonPropertiesForFlags: jest.fn(),
                reloadFeatureFlagsAsync: jest.fn(async () => ({})),
                register: jest.fn(),
                getSessionId: () => 'example-session',
            }) as unknown as PostHog
    )
    const previousKey = process.env.EXPO_PUBLIC_POSTHOG_KEY
    process.env.EXPO_PUBLIC_POSTHOG_KEY = 'phc_example'
    try {
        initAnalytics()
        const filter = jest.mocked(PostHog).mock.calls[0]?.[1]?.before_send
        if (typeof filter !== 'function') {
            throw new Error('Expected one event filter')
        }
        const opened = filter({
            event: 'Application Opened',
            properties: { url: 'posthog://callback?code=example-private-code&state=example-state', project_id: 99 },
        })
        expect(opened?.properties).toEqual(
            expect.objectContaining({
                client_surface: 'mobile',
                project_id: 7,
                deep_link_kind: 'callback',
                $groups: { organization: 'example-org', project: 'example-project' },
            })
        )
        expect(JSON.stringify(opened)).not.toContain('example-private-code')
        expect(opened?.properties).not.toHaveProperty('url')

        const record = actionTracker()
        useAuthStore.getState().projectId = 8
        record('mobile_session_sent')
        const [event, properties] = capture.mock.calls[0]
        expect(filter({ event, properties })?.properties).toEqual(
            expect.objectContaining({
                project_id: 7,
                $groups: { organization: 'example-org', project: 'example-project' },
            })
        )
    } finally {
        if (previousKey === undefined) {
            delete process.env.EXPO_PUBLIC_POSTHOG_KEY
        } else {
            process.env.EXPO_PUBLIC_POSTHOG_KEY = previousKey
        }
        useAuthStore.getState().projectId = 7
        setAnalyticsClient(null)
        setAnalyticsContextProvider(() => ({ identity: null, properties: {} }))
        setAnalyticsScreenContext({})
    }
})
