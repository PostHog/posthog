import type { ReactElement } from 'react'
import { Circle, Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function PersonIcon({ size = 14, color, strokeWidth = 2.2 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Circle cx={12} cy={9} r={3.5} />
            <Path d="M6 20c0-3.3 2.7-6 6-6s6 2.7 6 6" />
        </StrokeIcon>
    )
}
