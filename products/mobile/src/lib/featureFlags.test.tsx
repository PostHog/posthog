import { act, renderHook } from '@testing-library/react-native'
import * as React from 'react'

type FeatureFlagsModule = typeof import('./featureFlags')
type AuthStoreModule = typeof import('@/auth/authStore')

function loadFeatureFlags(isDev: boolean, forcedFlags = ''): FeatureFlagsModule & AuthStoreModule {
    ;(globalThis as unknown as { __DEV__: boolean }).__DEV__ = isDev
    process.env.EXPO_PUBLIC_FEATURE_FLAGS = forcedFlags
    let loaded: (FeatureFlagsModule & AuthStoreModule) | undefined
    jest.isolateModules(() => {
        jest.doMock('react', () => React)
        loaded = {
            ...jest.requireActual<FeatureFlagsModule>('./featureFlags'),
            ...jest.requireActual<AuthStoreModule>('@/auth/authStore'),
        }
    })
    if (!loaded) {
        throw new Error('feature flags module did not load')
    }
    return loaded
}

describe('mobile feature flags', () => {
    const globals = globalThis as unknown as { __DEV__: boolean }
    const originalDev = globals.__DEV__
    const originalForcedFlags = process.env.EXPO_PUBLIC_FEATURE_FLAGS
    const originalAnalyticsKey = process.env.EXPO_PUBLIC_POSTHOG_KEY

    beforeEach(() => {
        delete process.env.EXPO_PUBLIC_POSTHOG_KEY
    })

    afterEach(() => {
        globals.__DEV__ = originalDev
        jest.dontMock('react')
        if (originalForcedFlags === undefined) {
            delete process.env.EXPO_PUBLIC_FEATURE_FLAGS
        } else {
            process.env.EXPO_PUBLIC_FEATURE_FLAGS = originalForcedFlags
        }
        if (originalAnalyticsKey === undefined) {
            delete process.env.EXPO_PUBLIC_POSTHOG_KEY
        } else {
            process.env.EXPO_PUBLIC_POSTHOG_KEY = originalAnalyticsKey
        }
    })

    test.each([
        ['http://localhost:8010', true, true],
        ['http://127.0.0.1:8010', true, true],
        ['http://[::1]:8010', true, true],
        ['https://us.posthog.com', true, false],
        ['https://eu.posthog.com', true, false],
        ['https://posthog.example.com', true, false],
        ['http://127.0.0.2:8010', true, false],
        ['http://localhost:8010', false, false],
    ])('local product defaults for %s in development %s', (host, isDev, enabled) => {
        const { useAuthStore, useMobileProductFlags, useFeatureFlag, FEATURE_FLAGS, setFeatureFlags } =
            loadFeatureFlags(isDev)
        useAuthStore.setState({ status: 'signed_in', signedIn: true, host })
        setFeatureFlags({ [FEATURE_FLAGS.errorTracking]: false, [FEATURE_FLAGS.sessionReplay]: false })
        const { result } = renderHook(() => ({
            ...useMobileProductFlags(),
            modelSort: useFeatureFlag(FEATURE_FLAGS.modelScoreSort),
        }))
        expect(result.current).toEqual({ errors: enabled, replay: enabled, modelSort: false })
    })

    test('updates local defaults when a session signs in, switches host, and signs out', () => {
        const { useAuthStore, useMobileProductFlags } = loadFeatureFlags(true)
        useAuthStore.setState({ status: 'loading', signedIn: false, host: 'http://localhost:8010' })
        const { result } = renderHook(useMobileProductFlags)
        expect(result.current).toEqual({ errors: false, replay: false })

        act(() => useAuthStore.setState({ status: 'signed_in', signedIn: true }))
        expect(result.current).toEqual({ errors: true, replay: true })
        act(() => useAuthStore.setState({ host: 'https://us.posthog.com' }))
        expect(result.current).toEqual({ errors: false, replay: false })
        act(() => useAuthStore.setState({ host: 'http://localhost:8010' }))
        expect(result.current).toEqual({ errors: true, replay: true })
        act(() => useAuthStore.setState({ status: 'signed_out', signedIn: false }))
        expect(result.current).toEqual({ errors: false, replay: false })
    })

    test.each([true, false])('retains remote rollout values in development %s', (isDev) => {
        const { useAuthStore, useMobileProductFlags, useFeatureFlag, FEATURE_FLAGS, setFeatureFlags } =
            loadFeatureFlags(isDev)
        useAuthStore.setState({ status: 'signed_in', signedIn: true, host: 'https://us.posthog.com' })
        setFeatureFlags({
            [FEATURE_FLAGS.errorTracking]: false,
            [FEATURE_FLAGS.sessionReplay]: 'enabled-variant',
            [FEATURE_FLAGS.modelScoreSort]: true,
        })
        const { result } = renderHook(() => ({
            ...useMobileProductFlags(),
            modelSort: useFeatureFlag(FEATURE_FLAGS.modelScoreSort),
        }))
        expect(result.current).toEqual({ errors: false, replay: true, modelSort: true })
    })

    test.each([true, false])('limits explicit flag overrides to development %s', (isDev) => {
        const { useAuthStore, useMobileProductFlags, FEATURE_FLAGS, setFeatureFlags } = loadFeatureFlags(
            isDev,
            ' mobile-error-tracking, mobile-session-replay '
        )
        useAuthStore.setState({ status: 'signed_in', signedIn: true, host: 'https://us.posthog.com' })
        setFeatureFlags({ [FEATURE_FLAGS.errorTracking]: false, [FEATURE_FLAGS.sessionReplay]: false })
        const { result } = renderHook(useMobileProductFlags)
        expect(result.current).toEqual({ errors: isDev, replay: isDev })
    })
})
