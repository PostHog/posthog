import type { ReactElement } from 'react'
import { Circle, Rect } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function StopCircleIcon({ size = 20, color, strokeWidth = 2 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Circle cx={12} cy={12} r={9} />
            <Rect x={9} y={9} width={6} height={6} rx={1} />
        </StrokeIcon>
    )
}
