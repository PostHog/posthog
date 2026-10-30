import type { ReactElement } from 'react'
import { Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function ArrowDownIcon({ size = 16, color, strokeWidth = 2.2 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Path d="M12 5v14M6 13l6 6 6-6" />
        </StrokeIcon>
    )
}
