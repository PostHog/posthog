import type { ReactElement, RefObject } from 'react'
import { StyleSheet, View, type ViewInstance } from 'react-native'

import { BlurEdge } from './BlurEdge'
import { FadeEdge } from './FadeEdge'
import { useScreenBlurTarget } from './ScreenBlur'
import { layout } from './tokens'

export const HEADER_FADE = 8
const HEADER_BLUR_INTENSITY = 16.5

export function HeaderBackdrop({
    fadeStart,
    blurTarget,
}: {
    fadeStart: number
    blurTarget?: RefObject<ViewInstance | null>
}): ReactElement {
    const screenTarget = useScreenBlurTarget()
    const height = fadeStart + HEADER_FADE
    const solid = fadeStart / height
    return (
        <View style={[styles.backdrop, { height }]}>
            <BlurEdge solid={solid} intensity={HEADER_BLUR_INTENSITY} blurTarget={blurTarget ?? screenTarget} />
            <FadeEdge direction="down" solid={solid} opacity={layout.chromeTint} />
        </View>
    )
}

const styles = StyleSheet.create({
    backdrop: { position: 'absolute', top: 0, left: 0, right: 0, pointerEvents: 'none' },
})
