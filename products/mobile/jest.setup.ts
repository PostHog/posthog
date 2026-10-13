import type { MetricChartProps } from '@/ui/chart/types'

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
