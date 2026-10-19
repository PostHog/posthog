import type { ReactElement } from 'react'
import { Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function BrainIcon({ size = 20, color, strokeWidth = 1.8 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Path d="M12 5.5A3 3 0 0 0 6.5 5 3.5 3.5 0 0 0 4 10.5a3.5 3.5 0 0 0 1 6 4 4 0 0 0 7 2.5z" />
            <Path d="M12 5.5A3 3 0 0 1 17.5 5 3.5 3.5 0 0 1 20 10.5a3.5 3.5 0 0 1-1 6 4 4 0 0 1-7 2.5z" />
            <Path d="M8 10.5a2.5 2.5 0 0 0 2.5 2.5M16 10.5a2.5 2.5 0 0 1-2.5 2.5" />
        </StrokeIcon>
    )
}
