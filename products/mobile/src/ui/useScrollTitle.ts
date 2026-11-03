import { useCallback, useState } from 'react'
import type { LayoutChangeEvent, NativeScrollEvent, NativeSyntheticEvent } from 'react-native'
import { type SharedValue, useSharedValue } from 'react-native-reanimated'

import { SCREEN_CHROME_BOTTOM, SCREEN_CONTENT_TOP } from './screenLayout'

export interface ScrollTitle {
    text: string
    scrollY: SharedValue<number>
    revealEnd: number
}

export interface ScrollTitleState {
    title: ScrollTitle
    onTitleLayout: (event: LayoutChangeEvent) => void
    onScroll: (event: NativeSyntheticEvent<NativeScrollEvent>) => void
}

export function useScrollTitle(text: string): ScrollTitleState {
    const scrollY = useSharedValue(0)
    const [height, setHeight] = useState(0)
    const onTitleLayout = useCallback((event: LayoutChangeEvent): void => {
        setHeight(event.nativeEvent.layout.height)
    }, [])
    const onScroll = useCallback(
        (event: NativeSyntheticEvent<NativeScrollEvent>): void => {
            scrollY.value = event.nativeEvent.contentOffset.y
        },
        [scrollY]
    )
    return {
        title: { text, scrollY, revealEnd: height > 0 ? height + SCREEN_CONTENT_TOP - SCREEN_CHROME_BOTTOM : 0 },
        onTitleLayout,
        onScroll,
    }
}
