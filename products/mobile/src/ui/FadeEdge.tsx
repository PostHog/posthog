import { type ReactElement, useId } from 'react'
import { StyleSheet } from 'react-native'
import Svg, { Defs, LinearGradient, Rect, Stop } from 'react-native-svg'

import { type FadeCurve, fadeStops } from './fadeStops'
import { useColors } from './theme'

interface FadeEdgeProps {
    /** `down`: solid at the top, clear at the bottom. `up`: solid at the bottom, clear at the top. */
    direction: 'down' | 'up'
    solid: number
    curve?: FadeCurve
    color?: string
    /** Opacity of the solid part. Below 1 the content behind shows through, for use over a blur. */
    opacity?: number
}

// Drawn with SVG so no gradient dependency is needed.
export function FadeEdge({
    direction,
    solid,
    curve = 'linear',
    color: colorProp,
    opacity = 1,
}: FadeEdgeProps): ReactElement {
    const colors = useColors()
    const color = colorProp ?? colors.background
    const id = `fade${useId().replace(/[^a-zA-Z0-9]/g, '')}`
    const down = direction === 'down'
    return (
        <Svg style={styles.fill} width="100%" height="100%" preserveAspectRatio="none">
            <Defs>
                <LinearGradient id={id} x1="0" y1={down ? '0' : '1'} x2="0" y2={down ? '1' : '0'}>
                    {fadeStops(solid, curve).map((stop) => (
                        <Stop
                            key={stop.key}
                            offset={String(stop.offset)}
                            stopColor={color}
                            stopOpacity={opacity * stop.opacity}
                        />
                    ))}
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
