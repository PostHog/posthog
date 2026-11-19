import type { ReactElement } from 'react'
import { Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

/** The handoff draws the back and prev/next chevrons on a narrow 12x20 grid; `size` is the height. */
export function ChevronLeftIcon({ size = 15, color, strokeWidth = 2.4 }: IconProps): ReactElement {
    return (
        <StrokeIcon
            size={size}
            width={size * 0.6}
            height={size}
            viewBox="0 0 12 20"
            color={color}
            strokeWidth={strokeWidth}
        >
            <Path d="M10 2L2 10l8 8" />
        </StrokeIcon>
    )
}
