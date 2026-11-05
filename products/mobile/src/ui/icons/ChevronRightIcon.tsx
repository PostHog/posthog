import type { ReactElement } from 'react'
import { Path } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

/** Drawn on the same 12x20 grid as ChevronLeftIcon; `size` is the height. */
export function ChevronRightIcon({ size = 15, color, strokeWidth = 2.4 }: IconProps): ReactElement {
    return (
        <StrokeIcon
            size={size}
            width={size * 0.6}
            height={size}
            viewBox="0 0 12 20"
            color={color}
            strokeWidth={strokeWidth}
        >
            <Path d="M2 2l8 8-8 8" />
        </StrokeIcon>
    )
}
