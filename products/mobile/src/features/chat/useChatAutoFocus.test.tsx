import { act, render } from '@testing-library/react-native'
import { type ReactElement, useCallback } from 'react'
import { Platform, TextInput } from 'react-native'

import { useChatAutoFocus } from './useChatAutoFocus'

const mockNavigation = { addListener: jest.fn(), isFocused: jest.fn(() => true) }
jest.mock('expo-router', () => ({ useNavigation: () => mockNavigation }))
jest.mock('expo-router/react-navigation', () => ({ useIsFocused: () => mockNavigation.isFocused() }))

function Input({ autoFocus }: { autoFocus: boolean }): ReactElement {
    const ref = useCallback(
        (node: TextInput | null) => {
            if (autoFocus) {
                node?.focus()
            }
        },
        [autoFocus]
    )
    return <TextInput ref={ref} />
}

function Page({ visible = true, chatId = 'new' }: { visible?: boolean; chatId?: string }): ReactElement | null {
    const autoFocus = useChatAutoFocus()
    return visible ? <Input key={chatId} autoFocus={autoFocus} /> : null
}

describe('chat input focus', () => {
    const focus = jest.mocked(TextInput.prototype.focus)
    const unsubscribe = jest.fn()
    let transitionEnd: (event: { data: { closing: boolean } }) => void
    let blur: () => void

    beforeEach(() => {
        jest.clearAllMocks()
        mockNavigation.isFocused.mockReturnValue(true)
        mockNavigation.addListener.mockImplementation((event, listener) => {
            if (event === 'blur') {
                blur = listener
            } else {
                transitionEnd = listener
            }
            return unsubscribe
        })
    })
    afterEach(() => jest.restoreAllMocks())

    test.each(['ios', 'android'] as const)('waits for the opening transition on %s', (platform) => {
        jest.replaceProperty(Platform, 'OS', platform)
        const view = render(<Page />)
        expect(focus).not.toHaveBeenCalled()

        act(() => transitionEnd({ data: { closing: true } }))
        expect(focus).not.toHaveBeenCalled()
        act(() => transitionEnd({ data: { closing: false } }))
        expect(focus).toHaveBeenCalledTimes(1)

        view.rerender(<Page />)
        act(() => transitionEnd({ data: { closing: false } }))
        expect(focus).toHaveBeenCalledTimes(1)
        view.rerender(<Page chatId="another-chat" />)
        expect(focus).toHaveBeenCalledTimes(2)

        act(() => {
            mockNavigation.isFocused.mockReturnValue(false)
            blur()
        })
        mockNavigation.isFocused.mockReturnValue(true)
        view.rerender(<Page chatId="another-chat" />)
        expect(focus).toHaveBeenCalledTimes(2)
        act(() => transitionEnd({ data: { closing: false } }))
        expect(focus).toHaveBeenCalledTimes(3)
        view.unmount()
        expect(unsubscribe).toHaveBeenCalledTimes(2)
    })

    test.each([false, true])('handles the access gate showing the input after opening: %s', (afterOpening) => {
        const view = render(<Page visible={false} />)
        if (!afterOpening) {
            view.rerender(<Page />)
        }
        expect(focus).not.toHaveBeenCalled()
        act(() => transitionEnd({ data: { closing: false } }))
        if (afterOpening) {
            view.rerender(<Page />)
        }
        expect(focus).toHaveBeenCalledTimes(1)
    })

    test('does not open the keyboard when the page has lost focus', () => {
        render(<Page />)
        mockNavigation.isFocused.mockReturnValue(false)
        act(() => transitionEnd({ data: { closing: false } }))
        expect(focus).not.toHaveBeenCalled()
    })

    test('focuses on web where the native opening event is unavailable', () => {
        jest.replaceProperty(Platform, 'OS', 'web')
        render(<Page />)
        expect(focus).toHaveBeenCalledTimes(1)
    })
})
