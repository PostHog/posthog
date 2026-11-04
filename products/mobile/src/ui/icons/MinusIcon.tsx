import type { ReactElement } from 'react'
import { Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function MinusIcon({ size = 14, color, strokeWidth = 2.6 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Path d="M7 12h10" />
        </StrokeIcon>
    )
}
