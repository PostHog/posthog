import type { ReactElement } from 'react'
import { Circle, Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function ReassignIcon({ size = 18, color, strokeWidth = 2 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Circle cx={9} cy={8} r={3.5} />
            <Path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6" />
            <Path d="M17 5h4m0 0-2-2m2 2-2 2" />
        </StrokeIcon>
    )
}
