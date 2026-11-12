import type { ReactElement } from 'react'
import { Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

/** A pulse line, for the Live screen in the navigation, Browse and Settings. */
export function LiveIcon({ size = 18, color, strokeWidth = 1.8 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Path d="M3 12.5h3.6l2.6-6.5 5.2 12 2.6-5.5H21" />
        </StrokeIcon>
    )
}
