import type { ReactElement } from 'react'
import { Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function CheckIcon({ size = 18, color, strokeWidth = 2.4 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Path d="M20 6 9 17l-5-5" />
        </StrokeIcon>
    )
}
