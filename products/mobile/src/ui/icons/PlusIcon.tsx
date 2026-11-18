import type { ReactElement } from 'react'
import { Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function PlusIcon({ size = 16, color, strokeWidth = 2.2 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Path d="M12 5v14M5 12h14" />
        </StrokeIcon>
    )
}
