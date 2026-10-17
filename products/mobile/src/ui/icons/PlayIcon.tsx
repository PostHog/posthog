import type { ReactElement } from 'react'
import Svg, { Path } from 'react-native-svg'

import { colors } from '../tokens'
import type { IconProps } from './types'

export function PlayIcon({ size = 10, color = colors.white }: IconProps): ReactElement {
    return (
        <Svg width={size} height={size} viewBox="0 0 24 24" fill={color}>
            <Path d="M7 4l12 8-12 8z" />
        </Svg>
    )
}
