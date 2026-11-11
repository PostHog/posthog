import type { ReactElement } from 'react'
import { Ellipse, Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function DatabaseIcon({ size = 18, color, strokeWidth = 1.8 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Ellipse cx={12} cy={6} rx={7} ry={3} />
            <Path d="M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6" />
            <Path d="M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3" />
        </StrokeIcon>
    )
}
