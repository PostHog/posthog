import type { ReactElement } from 'react'
import { Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function ChevronUpIcon({ size = 16, color, strokeWidth = 2.4 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Path d="M6 15l6-6 6 6" />
        </StrokeIcon>
    )
}
