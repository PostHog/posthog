import { waitFor } from '@testing-library/react-native'
import PostHog, { type PostHogOptions, PostHogPersistedProperty } from 'posthog-react-native'
import { Linking } from 'react-native'

import { useAuthStore } from '@/auth/authStore'
import { useDemoMode } from '@/demo/demoMode'

import { setAnalyticsClient } from './analytics'
import { initAnalytics } from './posthogClient'

let mockSdkOptions: PostHogOptions = {}

jest.mock('posthog-react-native', () => {
    const sdk = jest.requireActual<typeof import('posthog-react-native')>('posthog-react-native')
    return {
        ...sdk,
        __esModule: true,
        default: jest.fn(
            (apiKey: string, options: PostHogOptions) =>
                new sdk.default(apiKey, {
                    ...options,
                    persistence: 'memory',
                    flushInterval: 0,
                    ...mockSdkOptions,
                })
        ),
    }
})

interface QueuedEvent {
    message: { event: string; properties: Record<string, unknown> }
}

describe('mobile SDK analytics privacy', () => {
    beforeEach(() => {
        mockSdkOptions = { preloadFeatureFlags: false, disableRemoteConfig: true }
    })
    test.each([
        'posthog://report/example-private-label?title=example-title',
        'posthog://callback?code=example-code&state=example-state',
    ])('omits the initial URL from the SDK queue for %s', async (url) => {
        const originalKey = process.env.EXPO_PUBLIC_POSTHOG_KEY
        process.env.EXPO_PUBLIC_POSTHOG_KEY = 'phc_example_mobile_test'
        const network = jest.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 200 }))
        const initialURL = jest.spyOn(Linking, 'getInitialURL').mockResolvedValue(url)
        const authSubscribe = jest.spyOn(useAuthStore, 'subscribe').mockReturnValue(() => {})
        const demoSubscribe = jest.spyOn(useDemoMode, 'subscribe').mockReturnValue(() => {})
        const demoHydrate = jest.spyOn(useDemoMode.persist, 'onFinishHydration').mockReturnValue(() => {})
        useAuthStore.setState({ status: 'signed_out', signedIn: false, user: null })
        jest.mocked(PostHog).mockClear()
        let client: PostHog | undefined
        try {
            initAnalytics()
            client = jest.mocked(PostHog).mock.results[0]?.value as PostHog
            await client.ready()
            await waitFor(() => {
                const queue = client?.getPersistedProperty<QueuedEvent[]>(PostHogPersistedProperty.Queue) ?? []
                const opened = queue.find(({ message }) => message.event === 'Application Opened')
                expect(opened).toBeDefined()
                expect(opened?.message.properties).not.toHaveProperty('url')
                expect(JSON.stringify(queue)).not.toContain(url)
            })
        } finally {
            await client?.shutdown()
            setAnalyticsClient(null)
            network.mockRestore()
            initialURL.mockRestore()
            authSubscribe.mockRestore()
            demoSubscribe.mockRestore()
            demoHydrate.mockRestore()
            if (originalKey === undefined) {
                delete process.env.EXPO_PUBLIC_POSTHOG_KEY
            } else {
                process.env.EXPO_PUBLIC_POSTHOG_KEY = originalKey
            }
        }
    })

    test.each([
        { status: 'signed_in', preference: true },
        { status: 'signed_in', preference: undefined },
        { status: 'loading', preference: undefined },
        { status: 'signed_out', preference: undefined },
    ] as const)(
        'clears persisted email before SDK hydration loads flags ($status, privacy $preference)',
        async ({ status, preference }) => {
            const originalKey = process.env.EXPO_PUBLIC_POSTHOG_KEY
            process.env.EXPO_PUBLIC_POSTHOG_KEY = 'phc_example_mobile_test'
            const network = jest.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
                const url = String(input)
                return new Response(
                    JSON.stringify(url.includes('/flags') ? { featureFlags: {} } : { hasFeatureFlags: true }),
                    { status: 200 }
                )
            })
            const initialURL = jest.spyOn(Linking, 'getInitialURL').mockResolvedValue(null)
            const authSubscribe = jest.spyOn(useAuthStore, 'subscribe').mockReturnValue(() => {})
            const demoSubscribe = jest.spyOn(useDemoMode, 'subscribe').mockReturnValue(() => {})
            const demoHydrate = jest.spyOn(useDemoMode.persist, 'onFinishHydration').mockReturnValue(() => {})
            let releaseStorage!: () => void
            const storageReady = new Promise<void>((resolve) => {
                releaseStorage = resolve
            })
            mockSdkOptions = {
                persistence: 'file',
                customStorage: {
                    getItem: async () => {
                        await storageReady
                        return JSON.stringify({
                            version: 'v1',
                            content: { [PostHogPersistedProperty.PersonProperties]: { email: 'previous@example.com' } },
                        })
                    },
                    setItem: jest.fn(),
                },
            }
            useAuthStore.setState({
                status,
                signedIn: status === 'signed_in',
                projectId: 2,
                user: {
                    id: 1,
                    uuid: 'example-user',
                    distinctId: 'example-user',
                    email: 'person@example.com',
                    name: 'Example',
                    anonymizeData: preference,
                },
            })
            jest.mocked(PostHog).mockClear()
            let client: PostHog | undefined
            try {
                initAnalytics()
                client = jest.mocked(PostHog).mock.results[0]?.value as PostHog
                expect(network).not.toHaveBeenCalled()
                releaseStorage()
                await client.ready()
                await client.reloadRemoteConfigAsync()
                await client.reloadFeatureFlagsAsync()
                const flagsRequests = network.mock.calls.filter(([input]) => String(input).includes('/flags'))
                expect(flagsRequests.length).toBeGreaterThan(0)
                for (const [, options] of flagsRequests) {
                    const body: { person_properties: { email: string | null; project_id: number | null } } = JSON.parse(
                        String(options?.body)
                    )
                    expect(body.person_properties).toMatchObject({
                        email: null,
                        project_id: status === 'signed_in' ? 2 : null,
                    })
                    expect(JSON.stringify(body)).not.toContain('previous@example.com')
                    expect(JSON.stringify(body)).not.toContain('person@example.com')
                }
            } finally {
                releaseStorage()
                await client?.shutdown()
                setAnalyticsClient(null)
                network.mockRestore()
                initialURL.mockRestore()
                authSubscribe.mockRestore()
                demoSubscribe.mockRestore()
                demoHydrate.mockRestore()
                if (originalKey === undefined) {
                    delete process.env.EXPO_PUBLIC_POSTHOG_KEY
                } else {
                    process.env.EXPO_PUBLIC_POSTHOG_KEY = originalKey
                }
            }
        }
    )
})
