import type { ReactElement } from 'react'
import { Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function MoonIcon({ size = 22, color, strokeWidth = 2 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </StrokeIcon>
    )
}
