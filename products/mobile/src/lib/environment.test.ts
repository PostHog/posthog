import { type AppVariant, environmentBadge, hostKind, resolveBuildVariant } from './environment'

type EnvironmentModule = typeof import('./environment')

function loadEnvironment({
    applicationId,
    configVariant,
    isDev,
}: {
    applicationId: string | null
    configVariant?: string
    isDev: boolean
}): EnvironmentModule {
    const globals = globalThis as unknown as { __DEV__: boolean }
    const previousDev = globals.__DEV__
    globals.__DEV__ = isDev
    let loaded: EnvironmentModule | undefined
    try {
        jest.isolateModules(() => {
            jest.doMock('expo-application', () => ({ applicationId }))
            jest.doMock('expo-constants', () => ({
                __esModule: true,
                default: { expoConfig: { extra: { appVariant: configVariant } } },
            }))
            jest.doMock('expo-updates', () => ({
                channel: 'preview',
                updateId: '0f9e8d7c-1111-4222-8333-944455556666',
                createdAt: new Date('2026-01-02T03:04:05Z'),
            }))
            loaded = jest.requireActual<EnvironmentModule>('./environment')
        })
    } finally {
        globals.__DEV__ = previousDev
    }
    if (!loaded) {
        throw new Error('environment module did not load')
    }
    return loaded
}

describe('environment', () => {
    test.each<[string, string | null, unknown, AppVariant]>([
        [
            'the bundle id wins over an update that says otherwise',
            'com.posthog.code.mobile.preview',
            'production',
            'preview',
        ],
        ['the store bundle id is production', 'com.posthog.code.mobile', 'development', 'production'],
        ['the Android store package is production', 'com.posthog.mobile', 'development', 'production'],
        ['the Android preview package wins over update config', 'com.posthog.mobile.preview', 'production', 'preview'],
        ['the Android development package wins over update config', 'com.posthog.mobile.dev', 'preview', 'development'],
        ['the web build reads extra', null, 'development', 'development'],
        ['an unknown bundle id falls back to extra', 'com.example.fork', 'preview', 'preview'],
        ['nothing known is production', null, 'staging', 'production'],
    ])('build variant: %s', (_name, appId, configVariant, expected) => {
        expect(resolveBuildVariant(appId, configVariant)).toBe(expected)
    })

    test.each([
        ['https://us.posthog.com', 'cloud-us'],
        ['https://EU.posthog.com', 'cloud-eu'],
        ['http://localhost:8010', 'local'],
        ['http://127.0.0.1:8000', 'local'],
        ['http://[::1]:8010', 'local'],
        ['http://127.0.0.2:8010', 'custom'],
        ['http://10.0.2.2:8010', 'custom'],
        ['https://posthog.example.com', 'custom'],
        ['https://us.posthog.com.example.com', 'custom'],
        ['not a url', 'custom'],
    ])('host kind of %s is %s', (host, expected) => {
        expect(hostKind(host)).toBe(expected)
    })

    test.each<[AppVariant, string | null, ReturnType<typeof environmentBadge>]>([
        ['production', 'https://us.posthog.com', null],
        ['production', null, null],
        ['production', 'https://posthog.example.com', null],
        ['production', 'http://localhost:8010', null],
        ['development', 'https://us.posthog.com', { tone: 'development', label: 'Dev build · US cloud' }],
        ['preview', 'http://localhost:8010', { tone: 'preview', label: 'Preview build · localhost:8010' }],
        ['preview', null, { tone: 'preview', label: 'Preview build' }],
    ])('ribbon for a %s build on %s', (variant, host, expected) => {
        expect(environmentBadge(variant, host)).toEqual(expected)
    })

    test('a preview binary is internal and redirects to its own scheme', () => {
        const env = loadEnvironment({ applicationId: 'com.posthog.code.mobile.preview', isDev: false })
        expect(env).toMatchObject({
            appVariant: 'preview',
            isInternalBuild: true,
            appScheme: 'posthog-preview',
            updateChannel: 'preview',
            updateId: '0f9e8d7c-1111-4222-8333-944455556666',
        })
    })

    test('a Metro bundle in a store-identity binary is internal but keeps the store scheme', () => {
        const env = loadEnvironment({ applicationId: 'com.posthog.code.mobile', isDev: true })
        expect(env).toMatchObject({ appVariant: 'development', isInternalBuild: true, appScheme: 'posthog' })
    })

    test('a store binary outside Metro is not internal', () => {
        const env = loadEnvironment({ applicationId: 'com.posthog.code.mobile', isDev: false })
        expect(env).toMatchObject({ appVariant: 'production', isInternalBuild: false, appScheme: 'posthog' })
    })
})
