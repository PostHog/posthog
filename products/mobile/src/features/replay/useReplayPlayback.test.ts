import { act, renderHook } from '@testing-library/react-native'

import { trackFullReplayOpened } from './replayAnalytics'
import { useReplayPlayback } from './useReplayPlayback'

jest.mock('./replayAnalytics', () => ({ trackFullReplayOpened: jest.fn() }))

test('opens one embedded player for repeated taps, then allows reopening after close', () => {
    const { result } = renderHook(() => useReplayPlayback('invented-session'))
    act(() => {
        result.current.open()
        result.current.open()
    })
    expect(result.current.visible).toBe(true)
    expect(trackFullReplayOpened).toHaveBeenCalledTimes(1)
    act(() => result.current.close())
    expect(result.current.visible).toBe(false)
    act(() => result.current.open())
    expect(result.current.visible).toBe(true)
    expect(trackFullReplayOpened).toHaveBeenCalledTimes(2)
})
