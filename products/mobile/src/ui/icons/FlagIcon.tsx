import type { ReactElement } from 'react'
import { Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function FlagIcon({ size = 22, color, strokeWidth = 2 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Path d="M5 21V4" />
            <Path d="M5 4h11l-2 4 2 4H5" />
        </StrokeIcon>
    )
}
