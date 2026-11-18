import { act, renderHook, waitFor } from '@testing-library/react-native'
import { isLiquidGlassAvailable } from 'expo-glass-effect'
import { AccessibilityInfo } from 'react-native'

import { useLiquidGlass } from './useLiquidGlass'

describe('useLiquidGlass', () => {
    afterEach(() => {
        jest.mocked(isLiquidGlassAvailable).mockReturnValue(false)
        jest.mocked(AccessibilityInfo.isReduceTransparencyEnabled).mockResolvedValue(false)
        jest.mocked(AccessibilityInfo.isDarkerSystemColorsEnabled).mockResolvedValue(false)
    })

    test.each<[string, boolean, boolean, boolean, boolean]>([
        ['draws glass where the system has it', true, false, false, true],
        ['keeps the solid card without system glass', false, false, false, false],
        ['keeps the solid card with Reduce Transparency on', true, true, false, false],
        ['keeps the solid card with Increase Contrast on', true, false, true, false],
    ])('%s', async (_name, available, reduceTransparency, increaseContrast, expected) => {
        jest.mocked(isLiquidGlassAvailable).mockReturnValue(available)
        jest.mocked(AccessibilityInfo.isReduceTransparencyEnabled).mockResolvedValue(reduceTransparency)
        jest.mocked(AccessibilityInfo.isDarkerSystemColorsEnabled).mockResolvedValue(increaseContrast)

        const { result } = renderHook(() => useLiquidGlass())

        expect(result.current).toBe(false)
        await act(async () => undefined)
        expect(result.current).toBe(expected)
    })

    test('turning on Reduce Transparency while the app runs brings the solid card back', async () => {
        jest.mocked(isLiquidGlassAvailable).mockReturnValue(true)
        const { result } = renderHook(() => useLiquidGlass())
        await waitFor(() => expect(result.current).toBe(true))

        const [, listener] = jest
            .mocked(AccessibilityInfo.addEventListener)
            .mock.calls.findLast(([event]) => event === 'reduceTransparencyChanged') as [string, (on: boolean) => void]
        act(() => listener(true))

        expect(result.current).toBe(false)
    })
})
