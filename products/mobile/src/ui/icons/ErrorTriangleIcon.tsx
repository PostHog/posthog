import type { ReactElement } from 'react'
import { Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function ErrorTriangleIcon({ size = 18, color, strokeWidth = 1.8 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Path d="M12 3l10 18H2z" />
            <Path d="M12 10v4" />
            <Path d="M12 17.5h.01" />
        </StrokeIcon>
    )
}
