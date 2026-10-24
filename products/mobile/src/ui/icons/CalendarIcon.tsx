import type { ReactElement } from 'react'
import { Path, Rect } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function CalendarIcon({ size = 20, color, strokeWidth = 1.8 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Rect x={3.5} y={5} width={17} height={15.5} rx={2.5} />
            <Path d="M3.5 10h17M8 3v4M16 3v4" />
        </StrokeIcon>
    )
}
