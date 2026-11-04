import type { ReactElement } from 'react'
import { Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function HomeIcon({ size = 22, color, strokeWidth = 2 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Path d="M4 10.2 12 4l8 6.2V19a1 1 0 0 1-1 1h-4v-5.5a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1V20H5a1 1 0 0 1-1-1z" />
        </StrokeIcon>
    )
}
