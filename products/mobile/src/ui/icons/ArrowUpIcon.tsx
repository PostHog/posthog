import type { ReactElement } from 'react'
import { Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function ArrowUpIcon({ size = 16, color, strokeWidth = 2.4 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Path d="M12 19V5M6 11l6-6 6 6" />
        </StrokeIcon>
    )
}
