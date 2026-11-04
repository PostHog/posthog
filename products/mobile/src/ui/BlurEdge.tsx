import MaskedView from '@react-native-masked-view/masked-view'
import { BlurView } from 'expo-blur'
import type { ReactElement, RefObject } from 'react'
import { Platform, StyleSheet, type View, type ViewStyle } from 'react-native'

import { FadeEdge } from './FadeEdge'
import { useColorSchemeName } from './theme'

interface BlurEdgeProps {
    direction?: 'down' | 'up'
    solid: number
    intensity?: number
    blurTarget?: RefObject<View | null>
}

const DEFAULT_INTENSITY = 11

export function BlurEdge({
    direction = 'down',
    solid,
    intensity = DEFAULT_INTENSITY,
    blurTarget,
}: BlurEdgeProps): ReactElement {
    const scheme = useColorSchemeName()
    const blur = (
        <BlurView
            style={[styles.fill, webMask(direction, solid)]}
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
        <MaskedView style={styles.fill} maskElement={<FadeEdge direction={direction} solid={solid} />}>
            {blur}
        </MaskedView>
    )
}

// The masked-view web shim draws its children without a mask, so the web build masks with CSS instead.
function webMask(direction: 'down' | 'up', solid: number): ViewStyle | undefined {
    if (Platform.OS !== 'web') {
        return undefined
    }
    const gradient = `linear-gradient(to ${direction === 'down' ? 'bottom' : 'top'}, #000 ${Math.round(solid * 100)}%, transparent 100%)`
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
