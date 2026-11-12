import type { ReactElement } from 'react'
import { Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

/** A lab flask, for Experiments in the navigation and Browse. */
export function FlaskIcon({ size = 18, color, strokeWidth = 1.8 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Path d="M9 3h6" />
            <Path d="M10 3v5.6L4.7 17.8A2.1 2.1 0 0 0 6.5 21h11a2.1 2.1 0 0 0 1.8-3.2L14 8.6V3" />
            <Path d="M7.3 14h9.4" />
        </StrokeIcon>
    )
}
