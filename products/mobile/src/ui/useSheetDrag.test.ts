import { act, renderHook } from '@testing-library/react-native'
import { PointerType, State } from 'react-native-gesture-handler'

import { type SheetDrag, useSheetDrag } from './useSheetDrag'

jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))
jest.mock('react-native-reanimated', () => ({
    useSharedValue: (value: number) => {
        const { useRef } = jest.requireActual<typeof import('react')>('react')
        return useRef({ value }).current
    },
}))

test('resets a completed drag when the visible sheet returns from an editor', () => {
    const onClose = jest.fn()
    const { result, rerender } = renderHook(
        ({ page }: { page: string | null }) => useSheetDrag(true, onClose, undefined, page),
        { initialProps: { page: 'hostname' } }
    )
    const pan = result.current.pan
    const event: Parameters<NonNullable<SheetDrag['pan']['handlers']['onEnd']>>[0] = {
        handlerTag: 1,
        state: State.END,
        oldState: State.ACTIVE,
        numberOfPointers: 1,
        pointerType: PointerType.TOUCH,
        x: 50,
        y: 100,
        absoluteX: 50,
        absoluteY: 100,
        translationX: 0,
        translationY: 100,
        velocityX: 0,
        velocityY: 0,
    }

    act(() => {
        pan.handlers.onUpdate?.({ ...event, state: State.ACTIVE })
        pan.handlers.onEnd?.(event, true)
    })
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(result.current.drag.value).toBe(100)

    rerender({ page: null })
    expect(result.current.drag.value).toBe(0)
})
