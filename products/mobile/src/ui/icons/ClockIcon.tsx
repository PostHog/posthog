import type { ReactElement } from 'react'
import { Circle, Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function ClockIcon({ size = 18, color, strokeWidth = 2 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Circle cx={12} cy={12} r={9} />
            <Path d="M12 7v5l3 2" />
        </StrokeIcon>
    )
}
