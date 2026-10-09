import type { ReactElement } from 'react'
import { Circle, Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function SearchIcon({ size = 18, color, strokeWidth = 2.4 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Circle cx={11} cy={11} r={7} />
            <Path d="m20 20-3.5-3.5" />
        </StrokeIcon>
    )
}
