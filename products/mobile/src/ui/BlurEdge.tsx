import MaskedViewComponent from '@react-native-masked-view/masked-view'
import { BlurView } from 'expo-blur'
import type { ComponentType, ReactElement, RefObject } from 'react'
import type { ViewInstance } from 'react-native'
import { Platform, StyleSheet, type ViewProps, type ViewStyle } from 'react-native'

import { FadeEdge } from './FadeEdge'
import { type FadeCurve, fadeStops } from './fadeStops'
import { useColorSchemeName } from './theme'

interface BlurEdgeProps {
    direction?: 'down' | 'up'
    solid: number
    curve?: FadeCurve
    intensity?: number
    blurTarget?: RefObject<ViewInstance | null>
}

const DEFAULT_INTENSITY = 11

// The upstream declaration extends NativeMethods, which React Native's generated types no longer export.
const MaskedView = MaskedViewComponent as unknown as ComponentType<ViewProps & { maskElement: ReactElement }>

export function BlurEdge({
    direction = 'down',
    solid,
    curve = 'linear',
    intensity = DEFAULT_INTENSITY,
    blurTarget,
}: BlurEdgeProps): ReactElement {
    const scheme = useColorSchemeName()
    const blur = (
        <BlurView
            style={[styles.fill, webMask(direction, solid, curve)]}
            intensity={intensity}
            tint={scheme}
            blurMethod="dimezisBlurView"
            blurTarget={Platform.OS === 'android' ? blurTarget : undefined}
        />
    )
    if (Platform.OS === 'web') {
        return blur
    }
    // Only the alpha of the mask element matters, so the fade doubles as the mask.
    return (
        <MaskedView style={styles.fill} maskElement={<FadeEdge direction={direction} solid={solid} curve={curve} />}>
            {blur}
        </MaskedView>
    )
}

// The masked-view web shim draws its children without a mask, so the web build masks with CSS instead.
function webMask(direction: 'down' | 'up', solid: number, curve: FadeCurve): ViewStyle | undefined {
    if (Platform.OS !== 'web') {
        return undefined
    }
    const stops = fadeStops(solid, curve)
        .map((stop) => `rgba(0, 0, 0, ${stop.opacity}) ${stop.offset * 100}%`)
        .join(', ')
    const gradient = `linear-gradient(to ${direction === 'down' ? 'bottom' : 'top'}, ${stops})`
    return { maskImage: gradient, WebkitMaskImage: gradient } as unknown as ViewStyle
}

const styles = StyleSheet.create({
    fill: {
        position: 'absolute',
        top: 0,
        right: 0,
        bottom: 0,
        left: 0,
        pointerEvents: 'none',
    },
})
