import { NativeModules } from 'react-native'

import { DEMO_REPLAY_CONFIG } from './demoReplay'

describe('demo replay native SDK boundary', () => {
    it('keeps native automatic recording disabled and cancels pending starts after a stop', async () => {
        jest.useFakeTimers()
        const network = jest
            .spyOn(globalThis, 'fetch')
            .mockResolvedValue(new Response(JSON.stringify({ featureFlags: {} }), { status: 200 }))
        const native = {
            setup: jest.fn().mockResolvedValue(undefined),
            startRecording: jest.fn().mockResolvedValue(undefined),
            stopRecording: jest.fn().mockResolvedValue(undefined),
            isEnabled: jest.fn().mockResolvedValue(false),
            setOptOut: jest.fn().mockResolvedValue(undefined),
            getSessionReplayDebugProperties: jest.fn().mockResolvedValue({}),
        }
        NativeModules.PosthogReactNativePlugin = native
        const { default: PostHog } = jest.requireActual<typeof import('posthog-react-native')>('posthog-react-native')
        const sdk = new PostHog('phc_example', {
            persistence: 'memory',
            captureAppLifecycleEvents: false,
            capturePushNotificationSubscriptions: false,
            capturePushNotificationOpened: false,
            enableSessionReplay: false,
            sessionReplayConfig: DEMO_REPLAY_CONFIG,
            preloadFeatureFlags: false,
            disableRemoteConfig: true,
            flushInterval: 0,
        })

        try {
            await sdk.startSessionRecording()
            expect(native.setup).toHaveBeenCalledWith(
                expect.any(String),
                expect.any(Object),
                expect.objectContaining({
                    sessionReplay: expect.objectContaining({
                        enabled: false,
                        sdkReplayConfig: expect.objectContaining({
                            maskAllTextInputs: true,
                            maskAllImages: true,
                            maskAllSandboxedViews: true,
                            captureLog: false,
                            captureNetworkTelemetry: false,
                            captureTouches: false,
                        }),
                    }),
                })
            )
            expect(native.startRecording).toHaveBeenCalledWith(true)
            await sdk.stopSessionRecording()
            expect(native.stopRecording).toHaveBeenCalledTimes(1)
            native.isEnabled.mockResolvedValue(true)
            await sdk.reloadFeatureFlagsAsync()
            await jest.advanceTimersByTimeAsync(30_000)
            expect(native.startRecording).toHaveBeenCalledTimes(1)
            await sdk.startSessionRecording()
            expect(native.setup).toHaveBeenCalledTimes(1)
            expect(native.startRecording).toHaveBeenCalledTimes(2)
        } finally {
            await sdk.shutdown()
            delete NativeModules.PosthogReactNativePlugin
            network.mockRestore()
            jest.useRealTimers()
        }
    })
})
