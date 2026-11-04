import { renderHook } from '@testing-library/react-native'
import { useVerticalBarEdgeIOS } from 'expo-status-bar'
import { Platform } from 'react-native'
import { useNativeRail } from './useNativeRail'

jest.mock('expo-status-bar', () => ({ useVerticalBarEdgeIOS: jest.fn() }))

describe('useNativeRail', () => {
    const originalPlatform = Platform.OS
    afterEach(() => {
        Platform.OS = originalPlatform
    })

    test.each([
        { platform: 'ios', edge: 'leading', native: true },
        { platform: 'ios', edge: 'trailing', native: true },
        { platform: 'ios', edge: null, native: false },
        { platform: 'android', edge: null, native: false },
    ] as const)('follows the system bar on $platform at $edge', ({ platform, edge, native }) => {
        Platform.OS = platform
        jest.mocked(useVerticalBarEdgeIOS).mockReturnValue(edge)
        const { result } = renderHook(useNativeRail)
        expect(result.current).toBe(native)
    })
})
