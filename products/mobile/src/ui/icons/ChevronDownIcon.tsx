import type { ReactElement } from 'react'
import { Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function ChevronDownIcon({ size = 14, color, strokeWidth = 2.6 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Path d="M6 9l6 6 6-6" />
        </StrokeIcon>
    )
}
