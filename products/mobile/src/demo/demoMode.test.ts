import AsyncStorage from '@react-native-async-storage/async-storage'

type DemoStore = typeof import('./demoMode').useDemoMode

const globals = globalThis as unknown as { __DEV__: boolean }
const originalDev = globals.__DEV__
const originalDemoEnv = process.env.EXPO_PUBLIC_DEMO_MODE

describe('demo availability', () => {
    afterEach(async () => {
        globals.__DEV__ = originalDev
        if (originalDemoEnv === undefined) {
            delete process.env.EXPO_PUBLIC_DEMO_MODE
        } else {
            process.env.EXPO_PUBLIC_DEMO_MODE = originalDemoEnv
        }
        await AsyncStorage.clear()
    })

    test.each<[string, boolean, string | undefined, boolean | null, boolean]>([
        ['release restores a saved demo session', false, undefined, true, true],
        ['release ignores the demo environment flag', false, '1', null, false],
        ['release restores a saved demo session and ignores the environment flag', false, '1', true, true],
        ['development starts in demo from the environment', true, '1', null, true],
        ['development respects a saved exit from demo', true, '1', false, false],
        ['development restores a demo session', true, undefined, true, true],
        ['development defaults to live data', true, undefined, null, false],
    ])('%s', async (_name, isDev, demoEnv, savedEnabled, expectedEnabled) => {
        if (demoEnv === undefined) {
            delete process.env.EXPO_PUBLIC_DEMO_MODE
        } else {
            process.env.EXPO_PUBLIC_DEMO_MODE = demoEnv
        }
        if (savedEnabled !== null) {
            await AsyncStorage.setItem(
                'posthog-mobile-demo',
                JSON.stringify({ state: { enabled: savedEnabled }, version: 0 })
            )
        }
        globals.__DEV__ = isDev
        let store: DemoStore | undefined
        jest.isolateModules(() => {
            store = jest.requireActual<typeof import('./demoMode')>('./demoMode').useDemoMode
        })
        if (!store) {
            throw new Error('Demo store did not load')
        }
        await store.persist.rehydrate()
        expect(store.getState().enabled).toBe(expectedEnabled)

        store.getState().setEnabled(true)
        expect(store.getState().enabled).toBe(true)
    })
})
