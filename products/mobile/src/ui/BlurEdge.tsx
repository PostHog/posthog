import MaskedView from '@react-native-masked-view/masked-view'
import { BlurView } from 'expo-blur'
import type { ReactElement } from 'react'
import { Platform, StyleSheet, type ViewStyle } from 'react-native'

import { FadeEdge } from './FadeEdge'

interface BlurEdgeProps {
    /** Fraction of the height, from the top, where the blur is full. Below it the blur dissolves to nothing. */
    solid: number
    intensity?: number
}

const DEFAULT_INTENSITY = 30

/** Blurs what scrolls under floating chrome. The blur dissolves at the bottom, so content softens instead of ending at a hard line. */
export function BlurEdge({ solid, intensity = DEFAULT_INTENSITY }: BlurEdgeProps): ReactElement {
    const blur = (
        <BlurView
            style={[styles.fill, webMask(solid)]}
            intensity={intensity}
            tint="light"
            experimentalBlurMethod="dimezisBlurView"
        />
    )
    if (Platform.OS === 'web') {
        return blur
    }
    // Only the alpha of the mask element matters, so the fade doubles as the mask.
    return (
        <MaskedView style={styles.fill} maskElement={<FadeEdge direction="down" solid={solid} />}>
            {blur}
        </MaskedView>
    )
}

// The masked-view web shim draws its children without a mask, so the web build masks with CSS instead.
function webMask(solid: number): ViewStyle | undefined {
    if (Platform.OS !== 'web') {
        return undefined
    }
    const gradient = `linear-gradient(to bottom, #000 ${Math.round(solid * 100)}%, transparent 100%)`
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
