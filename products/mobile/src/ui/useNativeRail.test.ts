import { act, cleanupAsync, renderHookAsync } from '@testing-library/react-native'
import type { VerticalBarEdgeIOS } from 'expo-status-bar'
import { Platform } from 'react-native'
import { useNativeRail } from './useNativeRail'

const mockSubscribe = jest.fn()
const mockSynchronousRead = jest.fn()
const mockRemove = jest.fn()
let onChange: (event: { edge: VerticalBarEdgeIOS | null }) => void

jest.mock('expo', () => ({
    requireOptionalNativeModule: () => ({
        addListener: (_event: string, listener: typeof onChange) => mockSubscribe(listener),
        getVerticalBarEdge: () => mockSynchronousRead(),
    }),
}))

describe('useNativeRail', () => {
    const originalPlatform = Platform.OS
    beforeEach(() => {
        Platform.OS = 'ios'
        jest.clearAllMocks()
        mockSubscribe.mockImplementation((listener: typeof onChange) => {
            onChange = listener
            return { remove: mockRemove }
        })
    })
    afterEach(async () => {
        await cleanupAsync()
        Platform.OS = originalPlatform
    })

    test('receives the initial rail and fold changes without a synchronous native read', async () => {
        const { result } = await renderHookAsync(useNativeRail)
        expect(result.current).toBe(false)
        for (const edge of ['leading', 'trailing', null] as const) {
            await act(async () => onChange({ edge }))
            expect(result.current).toBe(edge !== null)
        }
        expect(mockSynchronousRead).not.toHaveBeenCalled()
    })

    test('shares the current edge and native subscription across screens', async () => {
        const first = await renderHookAsync(useNativeRail)
        await act(async () => onChange({ edge: 'trailing' }))
        const second = await renderHookAsync(useNativeRail)
        expect(second.result.current).toBe(true)
        expect(mockSubscribe).toHaveBeenCalledTimes(1)
        await first.unmountAsync()
        expect(mockRemove).not.toHaveBeenCalled()
        await act(async () => onChange({ edge: null }))
        expect(second.result.current).toBe(false)
        await second.unmountAsync()
        expect(mockRemove).toHaveBeenCalledTimes(1)
    })

    test('does not subscribe on Android', async () => {
        Platform.OS = 'android'
        const { result } = await renderHookAsync(useNativeRail)
        expect(result.current).toBe(false)
        expect(mockSubscribe).not.toHaveBeenCalled()
    })
})
