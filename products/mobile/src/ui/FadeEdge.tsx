import { type ReactElement, useId } from 'react'
import { StyleSheet } from 'react-native'
import Svg, { Defs, LinearGradient, Rect, Stop } from 'react-native-svg'

import { useColors } from './theme'

interface FadeEdgeProps {
    /** `down`: solid at the top, clear at the bottom. `up`: solid at the bottom, clear at the top. */
    direction: 'down' | 'up'
    solid: number
    color?: string
    /** Opacity of the solid part. Below 1 the content behind shows through, for use over a blur. */
    opacity?: number
}

// Drawn with SVG so no gradient dependency is needed.
export function FadeEdge({ direction, solid, color: colorProp, opacity = 1 }: FadeEdgeProps): ReactElement {
    const colors = useColors()
    const color = colorProp ?? colors.background
    const id = `fade${useId().replace(/[^a-zA-Z0-9]/g, '')}`
    const down = direction === 'down'
    return (
        <Svg style={styles.fill} width="100%" height="100%" preserveAspectRatio="none">
            <Defs>
                <LinearGradient id={id} x1="0" y1={down ? '0' : '1'} x2="0" y2={down ? '1' : '0'}>
                    <Stop offset="0" stopColor={color} stopOpacity={opacity} />
                    <Stop offset={String(solid)} stopColor={color} stopOpacity={opacity} />
                    <Stop offset="1" stopColor={color} stopOpacity={0} />
                </LinearGradient>
            </Defs>
            <Rect x="0" y="0" width="100%" height="100%" fill={`url(#${id})`} />
        </Svg>
    )
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
