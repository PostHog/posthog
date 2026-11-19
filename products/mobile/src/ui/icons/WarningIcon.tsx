import type { ReactElement } from 'react'
import { Circle, Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function WarningIcon({ size = 22, color, strokeWidth = 2 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Circle cx={12} cy={12} r={9} />
            <Path d="M12 7.5v5.5" />
            <Path d="M12 16.5h.01" />
        </StrokeIcon>
    )
}
