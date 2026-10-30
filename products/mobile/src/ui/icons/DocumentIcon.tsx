import type { ReactElement } from 'react'
import { Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function DocumentIcon({ size = 18, color, strokeWidth = 1.8 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Path d="M6 3h8l4 4v14H6z" />
            <Path d="M14 3v4h4" />
            <Path d="M9 13h6M9 17h6" />
        </StrokeIcon>
    )
}
