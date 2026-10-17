import type { ReactElement } from 'react'
import { Circle, Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function InfoIcon({ size = 22, color, strokeWidth = 2 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Circle cx={12} cy={12} r={9} />
            <Path d="M12 11v5.5M12 7.6h.01" />
        </StrokeIcon>
    )
}
