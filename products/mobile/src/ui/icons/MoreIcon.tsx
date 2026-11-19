import type { ReactElement } from 'react'
import Svg, { Circle } from 'react-native-svg'

import { useColors } from '../theme'
import type { IconProps } from './types'

export function MoreIcon({ size = 22, color }: IconProps): ReactElement {
    const colors = useColors()
    return (
        <Svg width={size} height={size} viewBox="0 0 24 24" fill={color ?? colors.ink}>
            <Circle cx={5} cy={12} r={2} />
            <Circle cx={12} cy={12} r={2} />
            <Circle cx={19} cy={12} r={2} />
        </Svg>
    )
}
