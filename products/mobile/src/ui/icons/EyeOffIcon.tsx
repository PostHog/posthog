import type { ReactElement } from 'react'
import { Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function EyeOffIcon({ size = 18, color, strokeWidth = 2 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Path d="M10.7 5.1A10.7 10.7 0 0 1 21.9 11.7a1 1 0 0 1 0 .7 10.8 10.8 0 0 1-1.4 2.5" />
            <Path d="M14.1 14.2a3 3 0 0 1-4.2-4.2" />
            <Path d="M17.5 17.5A10.8 10.8 0 0 1 2.1 12.3a1 1 0 0 1 0-.7 10.8 10.8 0 0 1 4.4-5.1" />
            <Path d="m2 2 20 20" />
        </StrokeIcon>
    )
}
