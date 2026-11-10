jest.mock('@/auth/authStore', () => ({ useAuthStore: { getState: jest.fn(), subscribe: jest.fn() } }))
jest.mock('@/demo/demoMode', () => ({
    useDemoMode: {
        getState: jest.fn(),
        subscribe: jest.fn(),
        persist: { hasHydrated: jest.fn(), onFinishHydration: jest.fn() },
    },
}))
jest.mock('./featureFlags', () => ({ setFeatureFlags: jest.fn() }))
jest.mock('posthog-react-native', () =>
    jest.fn(() => ({
        register: jest.fn(),
        onFeatureFlags: jest.fn(),
        getFeatureFlags: () => ({}),
        resetPersonPropertiesForFlags: jest.fn(),
        setPersonPropertiesForFlags: jest.fn(),
        startSessionRecording: jest.fn().mockResolvedValue(undefined),
        stopSessionRecording: jest.fn().mockResolvedValue(undefined),
    }))
)

interface StoreMock {
    getState: jest.Mock
    subscribe: jest.Mock
}

interface DemoStoreMock extends StoreMock {
    persist: { hasHydrated: jest.Mock; onFinishHydration: jest.Mock }
}

interface SetupOptions {
    internal?: boolean
    platform?: string
    hydrated?: boolean
    demoEnabled?: boolean
    status?: string
    replay?: string
}

function setup({
    internal = true,
    platform = 'ios',
    hydrated = true,
    demoEnabled = true,
    status = 'signed_out',
    replay = '1',
}: SetupOptions = {}): {
    init: () => void
    auth: { status: string; host: null; projectId: null }
    demo: { enabled: boolean }
    authStore: StoreMock
    demoStore: DemoStoreMock
    constructor: jest.Mock
} {
    jest.resetModules()
    jest.doMock('./environment', () => ({
        isInternalBuild: internal,
        appVariant: 'development',
        hostKind: () => 'cloud-us',
    }))
    jest.doMock('react-native', () => ({
        AppState: { addEventListener: jest.fn() },
        Platform: { OS: platform },
    }))
    const authStore = jest.requireMock('@/auth/authStore').useAuthStore
    const demoStore = jest.requireMock('@/demo/demoMode').useDemoMode
    const auth = { status, host: null, projectId: null }
    const demo = { enabled: demoEnabled }
    authStore.getState.mockImplementation(() => auth)
    demoStore.getState.mockImplementation(() => demo)
    demoStore.persist.hasHydrated.mockReturnValue(hydrated)
    process.env.EXPO_PUBLIC_POSTHOG_KEY = 'phc_example'
    process.env.EXPO_PUBLIC_POSTHOG_REPLAY = replay
    const { initAnalytics } = jest.requireActual<typeof import('./posthogClient')>('./posthogClient')
    return {
        init: initAnalytics,
        auth,
        demo,
        authStore,
        demoStore,
        constructor: jest.requireMock('posthog-react-native'),
    }
}

describe('mobile replay integration', () => {
    afterEach(() => {
        delete process.env.EXPO_PUBLIC_POSTHOG_KEY
        delete process.env.EXPO_PUBLIC_POSTHOG_REPLAY
    })

    it.each<SetupOptions>([
        { internal: false },
        { platform: 'web' },
        { replay: '' },
        { hydrated: false },
        { demoEnabled: false },
        { status: 'signed_in' },
        { status: 'loading' },
    ])('does not start outside the demo recording boundary: %j', (options) => {
        const app = setup(options)
        app.init()
        expect(app.constructor.mock.results[0]?.value.startSessionRecording).not.toHaveBeenCalled()
    })

    it('starts after hydration, stops on leaving demo and sign-in, and creates one SDK client', () => {
        const app = setup({ hydrated: false })
        app.init()
        const sdk = app.constructor.mock.results[0]?.value
        expect(app.constructor).toHaveBeenCalledWith(
            'phc_example',
            expect.objectContaining({
                enableSessionReplay: false,
                capturePushNotificationSubscriptions: false,
                capturePushNotificationOpened: false,
                rageClickConfig: { enabled: false },
                sessionReplayConfig: expect.objectContaining({
                    maskAllTextInputs: true,
                    maskAllImages: true,
                    maskAllSandboxedViews: true,
                    captureLog: false,
                    captureNetworkTelemetry: false,
                    captureTouches: false,
                }),
            })
        )
        app.demoStore.persist.hasHydrated.mockReturnValue(true)
        app.demoStore.persist.onFinishHydration.mock.calls[0][0]()
        expect(sdk.startSessionRecording).toHaveBeenCalledTimes(1)
        app.demo.enabled = false
        app.demoStore.subscribe.mock.calls[0][0](app.demo, { enabled: true })
        expect(sdk.stopSessionRecording).toHaveBeenCalledTimes(1)
        app.demo.enabled = true
        app.demoStore.subscribe.mock.calls[0][0](app.demo, { enabled: false })
        expect(sdk.startSessionRecording).toHaveBeenCalledTimes(2)
        app.auth.status = 'signed_in'
        app.authStore.subscribe.mock.calls[0][0](app.auth, { ...app.auth, status: 'signed_out' })
        expect(sdk.stopSessionRecording).toHaveBeenCalledTimes(2)
        app.init()
        expect(app.constructor).toHaveBeenCalledTimes(1)
    })
})
