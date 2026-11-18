import type { ReactElement } from 'react'
import { Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function ExpandIcon({ size = 18, color, strokeWidth = 2 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
        </StrokeIcon>
    )
}
