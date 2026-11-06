import { renderHook } from '@testing-library/react-native'

import { usePickerCardStyle } from './usePickerCardStyle'

jest.mock('react-native-keyboard-controller', () => ({
    useReanimatedKeyboardAnimation: () => ({ height: { value: -235 } }),
}))
jest.mock('react-native-reanimated', () => ({
    useAnimatedStyle: (update: () => object) => update(),
}))
jest.mock('./useSceneDimensions', () => ({
    useSceneDimensions: () => ({ width: 874, height: 393 }),
}))
jest.mock('./useScreenInsets', () => ({
    useScreenInsets: () => ({ top: 52, bottom: 0, left: 0, right: 0 }),
}))

test('keeps a picker above the keyboard when less than 120 points remain', () => {
    const { result } = renderHook(() => usePickerCardStyle(90, 320))
    expect(result.current).toMatchObject({ top: 56, height: 98 })
    const style = result.current as { top: number; height: number }
    expect(style.top + style.height).toBeLessThan(393 - 235)
})
