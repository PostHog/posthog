import type { ReactElement } from 'react'
import { Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function RocketIcon({ size = 20, color, strokeWidth = 2 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Path d="M12 15l-3-3a13 13 0 0 1 11-9 13 13 0 0 1-8 12z" />
            <Path d="M9 12H5.5l2-4H11M12 15v3.5l4-2V13" />
            <Path d="M6 16.5C4.5 18 4.5 19.5 4.5 19.5s1.5 0 3-1.5" />
        </StrokeIcon>
    )
}
