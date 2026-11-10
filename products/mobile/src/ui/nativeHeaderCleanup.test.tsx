import { render } from '@testing-library/react-native'
import type { ReactElement } from 'react'
import { View } from 'react-native'
import { NativeChatChrome } from '@/features/chat/NativeChatChrome'
import { NativeTabChrome } from '@/features/tabs/NativeTabChrome'
import { NativeScreenChrome } from './NativeScreenChrome'

let mockOptions: Record<string, unknown> = {}
const mockNavigation = { setOptions: (options: Record<string, unknown>) => Object.assign(mockOptions, options) }

jest.mock('expo-router', () => {
    const { useLayoutEffect } = jest.requireActual<typeof import('react')>('react')
    const Screen = ({ options }: { options: Record<string, unknown> }): null => {
        useLayoutEffect(() => {
            mockNavigation.setOptions(options)
        }, [options])
        return null
    }
    const Toolbar = Object.assign(() => null, { Button: () => null })
    return { Stack: { Screen, Toolbar }, useNavigation: () => mockNavigation, useRouter: () => ({ push: jest.fn() }) }
})

const noop = (): void => undefined
const chromes: [string, ReactElement][] = [
    ['screen', <NativeScreenChrome key="screen" onBack={noop} backTestID="back" />],
    ['chat', <NativeChatChrome key="chat" onBack={noop} onMore={noop} onNewChat={noop} hasActions />],
    ['tab', <NativeTabChrome key="tab" slot={null} onMore={noop} />],
]

describe('native header lifecycle', () => {
    test.each(chromes)('hides the %s header and restores back gestures when the rail disappears', (_name, chrome) => {
        mockOptions = {}
        const view = render(chrome)
        expect(mockOptions.headerShown).toBe(true)
        view.rerender(<View />)
        expect(mockOptions).toMatchObject({ headerShown: false, gestureEnabled: true })
        view.rerender(chrome)
        expect(mockOptions.headerShown).toBe(true)
    })
})
