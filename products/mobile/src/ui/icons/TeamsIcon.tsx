import type { ReactElement } from 'react'
import { Circle, Path, Rect } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function TeamsIcon({ size = 22, color, strokeWidth = 2 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Rect x={3} y={4} width={18} height={16} rx={3} />
            <Circle cx={12} cy={10} r={2.5} />
            <Path d="M7.5 17c.8-2 2.5-3 4.5-3s3.7 1 4.5 3" />
        </StrokeIcon>
    )
}
