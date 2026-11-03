import { act, renderHook } from '@testing-library/react-native'
import { BackHandler } from 'react-native'

import { useOverlayBack } from './useOverlayBack'

let mockFocused = true
jest.mock('expo-router', () => ({ useIsFocused: () => mockFocused }))

test('Android Back dismisses the top overlay before falling through to the page', () => {
    const handlers: Parameters<typeof BackHandler.addEventListener>[1][] = []
    const listener = jest.spyOn(BackHandler, 'addEventListener').mockImplementation((_event, handler) => {
        handlers.push(handler)
        return {
            remove: () => {
                handlers.splice(handlers.indexOf(handler), 1)
            },
        }
    })
    const pressBack = (): boolean =>
        [...handlers].reverse().some((handler) => handler({ type: 'hardwareBackPress', timeStamp: 0 }) === true)
    const closeOuter = jest.fn()
    const closeInner = jest.fn()
    const latestClose = jest.fn()
    const view = renderHook<void, { outer: boolean; inner: boolean; close: () => void }>(
        ({ outer, inner, close }) => {
            useOverlayBack(outer, close)
            useOverlayBack(inner, closeInner)
        },
        { initialProps: { outer: true, inner: false, close: closeOuter } }
    )
    try {
        view.rerender({ outer: true, inner: true, close: closeOuter })
        view.rerender({ outer: true, inner: true, close: latestClose })
        act(() => expect(pressBack()).toBe(true))
        expect(closeInner).toHaveBeenCalledTimes(1)
        expect(closeOuter).not.toHaveBeenCalled()
        expect(latestClose).not.toHaveBeenCalled()

        mockFocused = false
        view.rerender({ outer: true, inner: true, close: latestClose })
        expect(pressBack()).toBe(false)
        expect(closeInner).toHaveBeenCalledTimes(1)
        expect(latestClose).not.toHaveBeenCalled()

        mockFocused = true
        view.rerender({ outer: true, inner: true, close: latestClose })
        act(() => expect(pressBack()).toBe(true))
        expect(closeInner).toHaveBeenCalledTimes(2)

        view.rerender({ outer: true, inner: false, close: latestClose })
        act(() => expect(pressBack()).toBe(true))
        expect(latestClose).toHaveBeenCalledTimes(1)

        view.rerender({ outer: false, inner: false, close: latestClose })
        expect(pressBack()).toBe(false)
    } finally {
        mockFocused = true
        view.unmount()
        listener.mockRestore()
    }
})
