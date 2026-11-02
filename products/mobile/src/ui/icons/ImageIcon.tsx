import type { ReactElement } from 'react'
import { Circle, Path, Rect } from 'react-native-svg'

import { StrokeIcon } from './StrokeIcon'
import type { IconProps } from './types'

export function ImageIcon({ size = 18, color, strokeWidth = 1.8 }: IconProps): ReactElement {
    return (
        <StrokeIcon size={size} color={color} strokeWidth={strokeWidth}>
            <Rect x={3} y={4} width={18} height={16} rx={2} />
            <Circle cx={9} cy={10} r={1.6} />
            <Path d="m21 16-5-5-9 9" />
        </StrokeIcon>
    )
}
