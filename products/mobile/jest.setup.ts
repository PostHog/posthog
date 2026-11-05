import type { MetricChartProps } from '@/ui/chart/types'

// Use a deterministic 12-hour device preference, matching the en-US locale in Expo's mock.
jest.mock('expo-localization', () => {
    const localization = jest.requireActual<typeof import('expo-localization')>('expo-localization')
    return {
        ...localization,
        getCalendars: jest.fn(() => [{ ...localization.getCalendars()[0], uses24hourClock: false }]),
    }
})

jest.mock('expo-network', () => ({
    ...jest.requireActual<typeof import('expo-network')>('expo-network'),
    addNetworkStateListener: jest.fn(() => ({ remove: jest.fn() })),
    getNetworkStateAsync: jest.fn(async () => ({ isConnected: true })),
}))

jest.mock('@react-native-async-storage/async-storage', () =>
    jest.requireActual('@react-native-async-storage/async-storage/jest/async-storage-mock')
)

jest.mock('expo-router', () => ({
    ...jest.requireActual('expo-router'),
    useIsFocused: () => true,
}))

// Skia draws through a native module or CanvasKit wasm, and Jest has neither. A test that renders a screen with a
// chart gets an empty box of the same size and testID in its place.
jest.mock('@/ui/chart/MetricChartCanvas', () => {
    const { createElement } = jest.requireActual<typeof import('react')>('react')
    const { View } = jest.requireActual<typeof import('react-native')>('react-native')
    const { CHART_DEFAULT_HEIGHT } = jest.requireActual<typeof import('@/ui/chart/chartMath')>('@/ui/chart/chartMath')
    return {
        MetricChartCanvas: ({ testID, height, label }: MetricChartProps) =>
            createElement(View, {
                testID,
                accessibilityLabel: `${label} chart`,
                style: { height: height ?? CHART_DEFAULT_HEIGHT },
            }),
    }
})

// The native browser module is unavailable in Jest; retain its callbacks so screen tests can exercise rendering.
jest.mock('react-native-webview', () => {
    const { createElement } = jest.requireActual<typeof import('react')>('react')
    const { View } = jest.requireActual<typeof import('react-native')>('react-native')
    const WebView = (props: Record<string, unknown>): ReturnType<typeof createElement> => createElement(View, props)
    return { __esModule: true, default: WebView, WebView }
})
