import type { ReactElement } from 'react'
import Svg, { Path } from 'react-native-svg'

import { useColors } from '../theme'
import type { IconProps } from './types'

/** Defaults to `onInk`, for the glyph on an ink circle. */
export function PlayIcon({ size = 10, color }: IconProps): ReactElement {
    const colors = useColors()
    return (
        <Svg width={size} height={size} viewBox="0 0 24 24" fill={color ?? colors.onInk}>
            <Path d="M7 4l12 8-12 8z" />
        </Svg>
    )
}
