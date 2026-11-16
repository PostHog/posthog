import type { ReactElement } from 'react'
import { Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function CloseIcon({ size = 16, color, strokeWidth = 2.4 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Path d="M6 6l12 12M18 6 6 18" />
        </StrokeIcon>
    )
}
