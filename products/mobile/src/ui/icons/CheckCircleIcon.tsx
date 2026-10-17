import type { ReactElement } from 'react'
import { Circle, Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function CheckCircleIcon({ size = 18, color, strokeWidth = 2 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Circle cx={12} cy={12} r={9} />
            <Path d="m8.5 12 2.5 2.5 4.5-5" />
        </StrokeIcon>
    )
}
